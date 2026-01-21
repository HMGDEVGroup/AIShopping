//
//  Models.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//
import Foundation

struct ProductCandidate: Codable, Identifiable {
    let brand: String?
    let name: String
    let model: String?
    let upc: String?
    let canonical_query: String
    let confidence: Double

    // Computed id (not part of Codable)
    var id: String {
        // Stable-ish: use UPC if present, else brand+name+model
        if let upc, !upc.isEmpty { return "upc:\(upc)" }
        return "cand:\(brand ?? "")|\(name)|\(model ?? "")"
    }
}

struct IdentifyResponse: Codable {
    let primary: ProductCandidate
    let candidates: [ProductCandidate]
    let notes: String?
    let raw_model_output: String?
}

struct Offer: Codable, Identifiable {
    let merchant: String
    let url: String
    let price: Double
    let shipping: Double
    let tax_est: Double
    let total_delivered: Double
    let currency: String
    let is_membership_required: Bool
    let bundle_items: [String]?
    let match_confidence: Double

    // Computed id (not part of Codable)
    var id: String {
        "offer:\(merchant)|\(url)"
    }
}

struct OffersResponse: Codable {
    let offers: [Offer]
    let best_offer_index: Int
    let explanation: String
}
