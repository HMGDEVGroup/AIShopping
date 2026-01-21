//
//  OfferCard.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//

import SwiftUI

struct OfferCard: View {
    let offer: Offer
    let isBest: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(offer.merchant).bold()
                Spacer()
                if isBest { Text("BEST").bold().foregroundStyle(.green) }
            }

            Text(String(format: "Total: $%.2f", offer.total_delivered))

            if offer.is_membership_required {
                Text("Membership required").font(.footnote).foregroundStyle(.orange)
            }

            if let items = offer.bundle_items, !items.isEmpty {
                Text("Bundle: \(items.joined(separator: ", "))")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Link("Buy", destination: URL(string: offer.url)!)
        }
        .padding(.vertical, 6)
    }
}
