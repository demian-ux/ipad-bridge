"""Parser mínimo de HEVC: tipo de NAL, campos del SPS necesarios para el hvcC, y armado del hvcC + codec string.
Sin dependencias. Entrada: NAL units sin start code (bytes)."""
import struct

VPS, SPS, PPS, AUD, SEI_PREFIX, SEI_SUFFIX = 32, 33, 34, 35, 39, 40


def nal_type(nal):
    return (nal[0] >> 1) & 0x3F


def is_irap(t):
    return 16 <= t <= 23  # BLA / IDR / CRA: puntos de acceso aleatorio (keyframes)


class _Bits:
    def __init__(self, data):
        # Quitar bytes de prevención de emulación (00 00 03 -> 00 00)
        out, zeros = bytearray(), 0
        for b in data:
            if zeros >= 2 and b == 3:
                zeros = 0
                continue
            out.append(b)
            zeros = zeros + 1 if b == 0 else 0
        self.d, self.pos = bytes(out), 0

    def u(self, n):
        v = 0
        for _ in range(n):
            byte = self.d[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ue(self):
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
        return (1 << zeros) - 1 + (self.u(zeros) if zeros else 0)


def parse_sps(nal):
    """Devuelve los campos del SPS que necesita el hvcC."""
    b = _Bits(nal[2:])  # saltar cabecera NAL de 2 bytes
    b.u(4)                                   # sps_video_parameter_set_id
    max_sub_layers_minus1 = b.u(3)
    temporal_id_nesting = b.u(1)
    profile_space, tier, profile_idc = b.u(2), b.u(1), b.u(5)
    compat = b.u(32)
    constraint = b.u(48)
    level_idc = b.u(8)
    sub_profile = [b.u(1) for _ in range(max_sub_layers_minus1)]
    sub_level = [b.u(1) for _ in range(max_sub_layers_minus1)]
    # (los flags se leen intercalados en el estándar: profile_present, level_present por capa)
    if max_sub_layers_minus1 > 0:
        for _ in range(max_sub_layers_minus1, 8):
            b.u(2)
    for i in range(max_sub_layers_minus1):
        if sub_profile[i]:
            b.u(88)
        if sub_level[i]:
            b.u(8)
    b.ue()                                   # sps_seq_parameter_set_id
    chroma_format_idc = b.ue()
    if chroma_format_idc == 3:
        b.u(1)
    b.ue(); b.ue()                           # width, height
    if b.u(1):                               # conformance_window_flag
        b.ue(); b.ue(); b.ue(); b.ue()
    bit_depth_luma = b.ue() + 8
    bit_depth_chroma = b.ue() + 8
    return dict(profile_space=profile_space, tier=tier, profile_idc=profile_idc, compat=compat, constraint=constraint,
                level_idc=level_idc, num_temporal_layers=max_sub_layers_minus1 + 1, temporal_id_nested=temporal_id_nesting,
                chroma_format_idc=chroma_format_idc, bit_depth_luma=bit_depth_luma, bit_depth_chroma=bit_depth_chroma)


def build_hvcc(vps, sps, pps):
    """HEVCDecoderConfigurationRecord (ISO 14496-15) con los tres parameter sets, longitud de NAL de 4 bytes."""
    s = parse_sps(sps)
    rec = bytearray()
    rec.append(1)
    rec.append((s["profile_space"] << 6) | (s["tier"] << 5) | s["profile_idc"])
    rec += struct.pack(">I", s["compat"])
    rec += s["constraint"].to_bytes(6, "big")
    rec.append(s["level_idc"])
    rec += struct.pack(">H", 0xF000 | 0)                       # reserved(4)=1111 + min_spatial_segmentation_idc
    rec.append(0xFC | 0)                                        # reserved(6) + parallelismType
    rec.append(0xFC | s["chroma_format_idc"])
    rec.append(0xF8 | (s["bit_depth_luma"] - 8))
    rec.append(0xF8 | (s["bit_depth_chroma"] - 8))
    rec += struct.pack(">H", 0)                                 # avgFrameRate
    rec.append((0 << 6) | (s["num_temporal_layers"] << 3) | (s["temporal_id_nested"] << 2) | 3)  # lengthSizeMinusOne=3
    arrays = [(VPS, vps), (SPS, sps), (PPS, pps)]
    rec.append(len(arrays))
    for t, nal in arrays:
        rec.append(0x80 | t)                                    # array_completeness=1
        rec += struct.pack(">H", 1)
        rec += struct.pack(">H", len(nal)) + nal
    return bytes(rec), s


def codec_string(s):
    """'hvc1.2.4.L153.B0' (ISO 14496-15 Annex E) para WebCodecs/MSE."""
    space = "" if s["profile_space"] == 0 else chr(ord("A") + s["profile_space"] - 1)
    compat_rev = int(f"{s['compat']:032b}"[::-1], 2)
    cons = s["constraint"].to_bytes(6, "big")
    while len(cons) > 1 and cons[-1] == 0:
        cons = cons[:-1]
    return (f"hvc1.{space}{s['profile_idc']}.{compat_rev:X}.{'H' if s['tier'] else 'L'}{s['level_idc']}."
            + ".".join(f"{c:02X}" for c in cons))
