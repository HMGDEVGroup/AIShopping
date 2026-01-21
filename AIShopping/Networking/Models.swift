//
//  Models.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//
import Foundation

// MARK: - Identify

struct IdentifyResponse: Codable {
    let primary: ProductCandidate
    let candidates: [ProductCandidate]
    let notes: String?
    let raw_model_output: String?
}

struct ProductCandidate: Codable, Identifiable {
    let brand: String?
    let name: String
    let model: String?
    let upc: String?
    let canonical_query: String
    let confidence: Double

    // Stable id for SwiftUI lists
    var id: String {
        "\(canonical_query)|\(brand ?? "")|\(name)|\(model ?? "")|\(upc ?? "")"
    }
}

// MARK: - Offers

struct OffersResponse: Codable {
    let query: String
    let offers: [OfferItem]
    let raw: [String: String]?   // backend returns null currently; keep optional
}

struct OfferItem: Codable, Identifiable {
    let title: String
    let price: String?
    let source: String?
    let link: String?
    let thumbnail: String?
    let delivery: String?
    let rating: Double?
    let reviews: Int?

    // Stable id for SwiftUI lists
    var id: String {
        link ?? "\(title)|\(source ?? "")|\(price ?? "")"
    }
}
