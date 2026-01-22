import Foundation

// MARK: - Models

struct IdentifyResponse: Decodable {
    struct ProductCandidate: Decodable {
        let brand: String?
        let name: String
        let model: String?
        let upc: String?
        let canonical_query: String
        let confidence: Double
    }

    let primary: ProductCandidate
    let candidates: [ProductCandidate]
    let notes: String?
    let raw_model_output: String?
}

struct OffersResponse: Decodable {
    struct OfferItem: Decodable {
        let title: String
        let price: String?
        let price_value: Double?
        let source: String?
        let link: String?
        let thumbnail: String?
        let delivery: String?
        let rating: Double?
        let reviews: Int?
    }

    let query: String
    let offers: [OfferItem]
    let raw: [String: AnyDecodable]?
}

// Helps decode "raw" as arbitrary JSON if you ever choose to return it.
struct AnyDecodable: Decodable {}


// MARK: - API Errors

enum APIClientError: LocalizedError {
    case invalidURL
    case invalidResponse
    case serverError(status: Int, message: String)
    case rateLimited(message: String, retryAfterSeconds: Int?)
    case decodingError(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL"
        case .invalidResponse:
            return "Invalid server response"
        case .serverError(_, let message):
            return message
        case .rateLimited(let message, let retry):
            if let retry = retry {
                return "\(message) (retry after ~\(retry)s)"
            }
            return message
        case .decodingError(let msg):
            return msg
        }
    }
}

/// FastAPI error envelope variants you return:
/// - {"detail":"..."}
/// - {"detail":{...}}
struct FastAPIErrorEnvelope: Decodable {
    let detail: Detail

    enum Detail: Decodable {
        case string(String)
        case object([String: JSONValue])

        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            if let s = try? container.decode(String.self) {
                self = .string(s)
                return
            }
            if let o = try? container.decode([String: JSONValue].self) {
                self = .object(o)
                return
            }
            self = .string("Unknown error")
        }
    }
}

/// Tiny JSON value decoder for error objects
enum JSONValue: Decodable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let b = try? c.decode(Bool.self) { self = .bool(b); return }
        if let n = try? c.decode(Double.self) { self = .number(n); return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        if let a = try? c.decode([JSONValue].self) { self = .array(a); return }
        if let o = try? c.decode([String: JSONValue].self) { self = .object(o); return }
        self = .null
    }

    func stringValue() -> String? {
        if case .string(let s) = self { return s }
        return nil
    }

    func intValue() -> Int? {
        if case .number(let n) = self { return Int(n) }
        return nil
    }
}


// MARK: - Client

final class APIClient {
    static let shared = APIClient()

    // Change if needed
    private let baseURL = URL(string: "https://aishopping-api.onrender.com")!

    private let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 60
        cfg.timeoutIntervalForResource = 60
        return URLSession(configuration: cfg)
    }()

    private init() {}

    // MARK: Offers

    func fetchOffers(q: String, num: Int = 10, gl: String = "us", hl: String = "en", includeMembership: Bool = true) async throws -> OffersResponse {
        var comps = URLComponents(url: baseURL.appendingPathComponent("/v1/offers"), resolvingAgainstBaseURL: false)
        comps?.queryItems = [
            URLQueryItem(name: "q", value: q),
            URLQueryItem(name: "num", value: String(num)),
            URLQueryItem(name: "gl", value: gl),
            URLQueryItem(name: "hl", value: hl),
            URLQueryItem(name: "include_membership", value: includeMembership ? "true" : "false"),
            URLQueryItem(name: "ts", value: String(Int(Date().timeIntervalSince1970)))
        ]

        guard let url = comps?.url else { throw APIClientError.invalidURL }

        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("no-cache", forHTTPHeaderField: "Cache-Control")

        let (data, resp) = try await session.data(for: req)
        try handleHTTPErrorsIfAny(data: data, resp: resp)

        do {
            return try JSONDecoder().decode(OffersResponse.self, from: data)
        } catch {
            throw APIClientError.decodingError("Failed to decode offers response: \(error)")
        }
    }

    // MARK: Identify

    func identify(imageData: Data, filename: String = "image.png", mimeType: String = "image/png") async throws -> IdentifyResponse {
        let url = baseURL.appendingPathComponent("/v1/identify")

        var req = URLRequest(url: URL(string: "\(url.absoluteString)?ts=\(Int(Date().timeIntervalSince1970))")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("no-cache", forHTTPHeaderField: "Cache-Control")

        let boundary = "Boundary-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.appendString("--\(boundary)\r\n")
        body.appendString("Content-Disposition: form-data; name=\"image\"; filename=\"\(filename)\"\r\n")
        body.appendString("Content-Type: \(mimeType)\r\n\r\n")
        body.append(imageData)
        body.appendString("\r\n")
        body.appendString("--\(boundary)--\r\n")

        req.httpBody = body

        let (data, resp) = try await session.data(for: req)
        try handleHTTPErrorsIfAny(data: data, resp: resp)

        do {
            return try JSONDecoder().decode(IdentifyResponse.self, from: data)
        } catch {
            throw APIClientError.decodingError("Failed to decode identify response: \(error)")
        }
    }

    // MARK: - Error handling

    private func handleHTTPErrorsIfAny(data: Data, resp: URLResponse) throws {
        guard let http = resp as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }

        if (200...299).contains(http.statusCode) {
            return
        }

        // Attempt to decode FastAPI error envelope
        let envelope: FastAPIErrorEnvelope? = try? JSONDecoder().decode(FastAPIErrorEnvelope.self, from: data)

        // Pull message out
        var message = "Request failed (\(http.statusCode))"
        var retryAfter: Int? = nil

        if let env = envelope {
            switch env.detail {
            case .string(let s):
                message = s
            case .object(let obj):
                // Prefer "message" if present
                if let m = obj["message"]?.stringValue() { message = m }
                if let e = obj["error"]?.stringValue() {
                    // If message wasn't set, at least show error type
                    if message == "Request failed (\(http.statusCode))" { message = e }
                }
                if let ra = obj["retry_after_seconds"]?.intValue() { retryAfter = ra }
            }
        } else if let s = String(data: data, encoding: .utf8), !s.isEmpty {
            message = s
        }

        if http.statusCode == 429 {
            throw APIClientError.rateLimited(message: message, retryAfterSeconds: retryAfter)
        } else {
            throw APIClientError.serverError(status: http.statusCode, message: message)
        }
    }
}

// MARK: - Data helpers

private extension Data {
    mutating func appendString(_ s: String) {
        if let d = s.data(using: .utf8) {
            append(d)
        }
    }
}
