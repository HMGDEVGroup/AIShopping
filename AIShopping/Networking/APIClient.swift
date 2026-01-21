//
//  APIClient.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//
import Foundation
import UIKit

final class APIClient {
    // Replace with your Render service URL:
    private let baseURL = URL(string: "https://YOUR-RENDER-SERVICE.onrender.com")!

    func identify(image: UIImage) async throws -> IdentifyResponse {
        let url = baseURL.appendingPathComponent("/v1/identify")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"

        let boundary = "Boundary-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let imageData = image.pngData() ?? Data()
        var body = Data()

        func append(_ s: String) { body.append(s.data(using: .utf8)!) }

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"image\"; filename=\"upload.png\"\r\n")
        append("Content-Type: image/png\r\n\r\n")
        body.append(imageData)
        append("\r\n--\(boundary)--\r\n")

        req.httpBody = body

        let (data, _) = try await URLSession.shared.data(for: req)
        return try JSONDecoder().decode(IdentifyResponse.self, from: data)
    }

    func offers(canonicalQuery: String, includeMembership: Bool) async throws -> OffersResponse {
        let url = baseURL.appendingPathComponent("/v1/offers")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let payload: [String: Any] = [
            "canonical_query": canonicalQuery,
            "prefs": ["include_membership": includeMembership]
        ]
        req.httpBody = try JSONSerialization.data(withJSONObject: payload)

        let (data, _) = try await URLSession.shared.data(for: req)
        return try JSONDecoder().decode(OffersResponse.self, from: data)
    }
}
