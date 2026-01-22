import Foundation

final class APIClient {
    static let shared = APIClient()

    private init() {}

    private let baseURL = URL(string: "https://aishopping-api.onrender.com")!

    enum APIClientError: LocalizedError {
        case invalidURL
        case requestFailed(String)
        case serverError(status: Int, message: String)
        case decodingFailed(String)

        var errorDescription: String? {
            switch self {
            case .invalidURL:
                return "Invalid URL."
            case .requestFailed(let msg):
                return msg
            case .serverError(let status, let message):
                return "Server error (\(status)): \(message)"
            case .decodingFailed(let msg):
                return "Failed to decode response: \(msg)"
            }
        }
    }

    struct FastAPIDetailError: Decodable {
        let detail: Detail

        enum Detail: Decodable {
            case string(String)
            case validation([ValidationItem])
            case unknown

            init(from decoder: Decoder) throws {
                let container = try decoder.singleValueContainer()
                if let s = try? container.decode(String.self) {
                    self = .string(s)
                    return
                }
                if let arr = try? container.decode([ValidationItem].self) {
                    self = .validation(arr)
                    return
                }
                self = .unknown
            }
        }

        struct ValidationItem: Decodable {
            let loc: [Loc]
            let msg: String
            let type: String

            enum Loc: Decodable {
                case string(String)
                case int(Int)

                init(from decoder: Decoder) throws {
                    let c = try decoder.singleValueContainer()
                    if let s = try? c.decode(String.self) {
                        self = .string(s)
                    } else if let i = try? c.decode(Int.self) {
                        self = .int(i)
                    } else {
                        self = .string("?")
                    }
                }
            }
        }
    }

    private func decodeFastAPIError(_ data: Data) -> String? {
        if let decoded = try? JSONDecoder().decode(FastAPIDetailError.self, from: data) {
            switch decoded.detail {
            case .string(let s):
                return s
            case .validation(let items):
                let lines = items.map { item -> String in
                    let loc = item.loc.map { l -> String in
                        switch l {
                        case .string(let s): return s
                        case .int(let i): return "\(i)"
                        }
                    }.joined(separator: ".")
                    return "\(loc): \(item.msg)"
                }
                return lines.joined(separator: "\n")
            case .unknown:
                return nil
            }
        }

        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = obj["detail"] as? String {
            return detail
        }

        return nil
    }

    private func makeURL(path: String, queryItems: [URLQueryItem] = []) -> URL? {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        components?.path = path
        if !queryItems.isEmpty {
            components?.queryItems = queryItems
        }
        return components?.url
    }

    private func handleHTTPError(status: Int, data: Data) -> APIClientError {
        let msg = decodeFastAPIError(data) ?? String(data: data, encoding: .utf8) ?? "Unknown error"

        if status == 429 {
            return .serverError(
                status: status,
                message: "Rate limit reached. Please try again in a moment.\n\n\(msg)"
            )
        }

        return .serverError(status: status, message: msg)
    }

    func identify(imageData: Data, filename: String = "image.png") async throws -> IdentifyResponse {
        guard let url = makeURL(
            path: "/v1/identify",
            queryItems: [URLQueryItem(name: "ts", value: String(Int(Date().timeIntervalSince1970)))]
        ) else {
            throw APIClientError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")

        var body = Data()

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"image\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/png\r\n\r\n".data(using: .utf8)!)
        body.append(imageData)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw APIClientError.requestFailed("No HTTP response.")
        }

        if !(200...299).contains(http.statusCode) {
            throw handleHTTPError(status: http.statusCode, data: data)
        }

        do {
            return try JSONDecoder().decode(IdentifyResponse.self, from: data)
        } catch {
            throw APIClientError.decodingFailed(error.localizedDescription)
        }
    }

    func offers(query: String, num: Int = 10, gl: String = "us", hl: String = "en", includeMembership: Bool = true) async throws -> OffersResponse {
        guard let url = makeURL(
            path: "/v1/offers",
            queryItems: [
                URLQueryItem(name: "q", value: query),
                URLQueryItem(name: "num", value: String(max(1, min(num, 50)))),
                URLQueryItem(name: "gl", value: gl),
                URLQueryItem(name: "hl", value: hl),
                URLQueryItem(name: "include_membership", value: includeMembership ? "true" : "false"),
                URLQueryItem(name: "ts", value: String(Int(Date().timeIntervalSince1970)))
            ]
        ) else {
            throw APIClientError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw APIClientError.requestFailed("No HTTP response.")
        }

        if !(200...299).contains(http.statusCode) {
            throw handleHTTPError(status: http.statusCode, data: data)
        }

        do {
            return try JSONDecoder().decode(OffersResponse.self, from: data)
        } catch {
            throw APIClientError.decodingFailed(error.localizedDescription)
        }
    }
}
