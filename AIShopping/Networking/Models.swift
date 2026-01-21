//
//  Models.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//
import Foundation

struct ProductCandidate: Codable, Identifiable {
    let id: UUID
    let brand: String?
    let name: String
    let model: String?
    let upc: String?
    let canonical_query: String
    let confidence: Double

    // ✅ Decode-friendly UUID
    init(id: UUID = UUID(),
         brand: String? = nil,
         name: String,
         model: String? = nil,
         upc: String? = nil,
         canonical_query: String,
         confidence: Double) {
        self.id = id
        self.brand = brand
        self.name = name
        self.model = model
        self.upc = upc
        self.canonical_query = canonical_query
        self.confidence = confidence
    }
}

struct IdentifyResponse: Codable {
    let primary: ProductCandidate
    let candidates: [ProductCandidate]
    let notes: String?
    let raw_model_output: String?
}

struct Offer: Codable, Identifiable {
    let id: UUID
    let title: String
    let price: String?
    let source: String?
    let link: String?
    let thumbnail: String?
    let delivery: String?
    let rating: Double?
    let reviews: Int?

    init(id: UUID = UUID(),
         title: String,
         price: String? = nil,
         source: String? = nil,
         link: String? = nil,
         thumbnail: String? = nil,
         delivery: String? = nil,
         rating: Double? = nil,
         reviews: Int? = nil) {
        self.id = id
        self.title = title
        self.price = price
        self.source = source
        self.link = link
        self.thumbnail = thumbnail
        self.delivery = delivery
        self.rating = rating
        self.reviews = reviews
    }
}

struct OffersResponse: Codable {
    let query: String
    let offers: [Offer]
    let raw: [String: AnyCodable]?
}

/// ✅ Minimal “AnyCodable” helper so the optional `raw` dict can decode without crashing.
/// You can remove `raw` entirely if you prefer.
struct AnyCodable: Codable {}
