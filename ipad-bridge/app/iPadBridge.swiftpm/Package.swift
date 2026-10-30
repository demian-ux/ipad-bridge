// swift-tools-version: 5.9
// App nativa para Swift Playgrounds en el iPad. Abrir este paquete .swiftpm con Playgrounds y tocar Ejecutar.
import PackageDescription
import AppleProductTypes

let package = Package(
    name: "iPadBridge",
    platforms: [.iOS("16.0")],
    products: [
        .iOSApplication(
            name: "iPadBridge",
            targets: ["AppModule"],
            bundleIdentifier: "studio.oaki.ipadbridge",
            teamIdentifier: "",
            displayVersion: "1.0",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .bird),
            accentColor: .presetColor(.blue),
            supportedDeviceFamilies: [.pad],
            supportedInterfaceOrientations: [.landscapeLeft, .landscapeRight],
            capabilities: [
                .localNetwork(purposeString: "Recibe la pantalla de la PC por cable o red local", bonjourServiceTypes: [])
            ]
        )
    ],
    targets: [
        .executableTarget(name: "AppModule", path: ".")
    ]
)
