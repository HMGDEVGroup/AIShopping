//
//  APIClient.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//
import Foundation
import UIKit

final class APIClient {

    static let shared = APIClient()

    // ✅ Render backend
    private let baseURL = URL(string: "https://aishopping-api.onrender.com")!

    private init() {}

    // MARK: - Compatibility wrappers (so your existing UI compiles)

    /// Your UI calls: state.api.identify(image:)
    func identify(image: UIImage) async throws -> IdentifyResponse {
        return try await identifyProduct(from: image)
    }

    /// Your UI calls: state.api.offers(canonicalQuery:includeMembership:)
    /// We haven’t built the Offers backend yet, so this returns a clear error for now.
    func offers(canonicalQuery: String, includeMembership: Bool) async throws -> OffersResponse {
        throw NSError(
            domain: "APIClient",
            code: -1,
            userInfo: [NSLocalizedDescriptionKey: "Offers API not implemented yet. Next step is to build /v1/offers on the backend."]
        )
    }

    // MARK: - Identify Product (Upload Image -> /v1/identify)

    func identifyProduct(from uiImage: UIImage) async throws -> IdentifyResponse {

        let url = baseURL.appendingPathComponent("v1/identify")

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        guard let imageData = uiImage.pngData() else {
            throw URLError(.cannotDecodeContentData)
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        request.httpBody = createMultipartBody(
            boundary: boundary,
            fieldName: "image",          // ✅ MUST be "image" (matches FastAPI)
            fileName: "upload.png",
            mimeType: "image/png",
            fileData: imageData
        )

        // ✅ DEBUG PRINTS (requested)
        print("IDENTIFY URL:", request.url?.absoluteString ?? "nil")

        let (data, response) = try await URLSession.shared.data(for: request)

        // ✅ DEBUG PRINTS (requested)
        print("STATUS:", (response as? HTTPURLResponse)?.statusCode ?? -1)
        print("BODY:", String(data: data, encoding: .utf8) ?? "nil")

        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw NSError(
                domain: "APIClient",
                code: http.statusCode,
                userInfo: [
                    NSLocalizedDescriptionKey: "Server returned status \(http.statusCode)",
                    "body": String(data: data, encoding: .utf8) ?? ""
                ]
            )
        }

        let decoder = JSONDecoder()
        return try decoder.decode(IdentifyResponse.self, from: data)
    }

    // MARK: - Multipart Helper

    private func createMultipartBody(
        boundary: String,
        fieldName: String,
        fileName: String,
        mimeType: String,
        fileData: Data
    ) -> Data {

        var body = Data()

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(fileName)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n".data(using: .utf8)!)

        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        return body
    }
}
