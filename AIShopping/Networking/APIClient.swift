//
//  APIClient.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//
import Foundation
import UIKit

final class APIClient {

    private let baseURL: URL

    // ✅ Public init
    init(baseURL: URL = URL(string: "https://aishopping-api.onrender.com")!) {
        self.baseURL = baseURL
    }

    enum APIError: LocalizedError {
        case badURL
        case badResponse
        case serverError(status: Int, body: String)
        case decodeError(String)

        var errorDescription: String? {
            switch self {
            case .badURL: return "Bad URL"
            case .badResponse: return "Bad server response"
            case let .serverError(status, body):
                return "Server returned status \(status): \(body)"
            case let .decodeError(msg):
                return "Decode error: \(msg)"
            }
        }
    }

    // MARK: - Identify

    func identify(image: UIImage) async throws -> IdentifyResponse {
        guard let url = URL(string: "/v1/identify", relativeTo: baseURL) else {
            throw APIError.badURL
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "accept")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        guard let pngData = image.pngData() else {
            throw APIError.decodeError("Unable to create PNG data from UIImage")
        }

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"image\"; filename=\"image.png\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/png\r\n\r\n".data(using: .utf8)!)
        body.append(pngData)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        // ✅ Debug prints
        print("IDENTIFY URL:", request.url?.absoluteString ?? "nil")

        let (data, response) = try await URLSession.shared.data(for: request)

        // ✅ Debug prints
        print("STATUS:", (response as? HTTPURLResponse)?.statusCode ?? -1)
        print("BODY:", String(data: data, encoding: .utf8) ?? "nil")

        guard let http = response as? HTTPURLResponse else {
            throw APIError.badResponse
        }

        if !(200...299).contains(http.statusCode) {
            let bodyText = String(data: data, encoding: .utf8) ?? ""
            throw APIError.serverError(status: http.statusCode, body: bodyText)
        }

        do {
            return try JSONDecoder().decode(IdentifyResponse.self, from: data)
        } catch {
            throw APIError.decodeError(error.localizedDescription)
        }
    }

    // MARK: - Offers (REAL)

    func offers(canonicalQuery: String, includeMembership: Bool) async throws -> OffersResponse {
        var comps = URLComponents(url: baseURL.appendingPathComponent("/v1/offers"), resolvingAgainstBaseURL: false)
        comps?.queryItems = [
            URLQueryItem(name: "q", value: canonicalQuery),
            URLQueryItem(name: "num", value: "10"),
            URLQueryItem(name: "gl", value: "us"),
            URLQueryItem(name: "hl", value: "en"),
        ]

        guard let url = comps?.url else { throw APIError.badURL }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "accept")

        print("OFFERS URL:", request.url?.absoluteString ?? "nil")

        let (data, response) = try await URLSession.shared.data(for: request)

        print("STATUS:", (response as? HTTPURLResponse)?.statusCode ?? -1)
        print("BODY:", String(data: data, encoding: .utf8) ?? "nil")

        guard let http = response as? HTTPURLResponse else {
            throw APIError.badResponse
        }

        if !(200...299).contains(http.statusCode) {
            let bodyText = String(data: data, encoding: .utf8) ?? ""
            throw APIError.serverError(status: http.statusCode, body: bodyText)
        }

        do {
            return try JSONDecoder().decode(OffersResponse.self, from: data)
        } catch {
            throw APIError.decodeError(error.localizedDescription)
        }
    }
}
