//
//  Models.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//
import Foundation

// MARK: - Identify Models

struct ProductCandidate: Codable, Identifiable, Hashable {
    var id: UUID = UUID()

    let brand: String?
    let name: String
    let model: String?
    let upc: String?
    let canonical_query: String
    let confidence: Double

    enum CodingKeys: String, CodingKey {
        case brand, name, model, upc, canonical_query, confidence
    }
}

struct IdentifyResponse: Codable {
    let primary: ProductCandidate
    let candidates: [ProductCandidate]
    let notes: String?
    let raw_model_output: String?
}

// MARK: - Offers Models (matches /v1/offers)

struct OfferItem: Codable, Identifiable, Hashable {
    var id: UUID = UUID()

    let title: String
    let price: String?
    let source: String?
    let link: String?
    let thumbnail: String?
    let delivery: String?
    let rating: Double?
    let reviews: Int?

    enum CodingKeys: String, CodingKey {
        case title, price, source, link, thumbnail, delivery, rating, reviews
    }
}

struct OffersResponse: Codable {
    let query: String
    let offers: [OfferItem]
    let raw: [String: String]? // backend returns null, so Optional is fine
}
