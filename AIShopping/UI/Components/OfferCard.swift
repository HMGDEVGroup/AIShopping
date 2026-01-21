//
//  OfferCard.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//

import SwiftUI

struct OfferCard: View {
    let offer: OfferItem
    let isBest: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {

            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(offer.source ?? "Unknown store")
                        .font(.headline)

                    Text(offer.title)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }

                Spacer()

                if isBest {
                    Text("BEST")
                        .font(.caption)
                        .bold()
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.green.opacity(0.2))
                        .clipShape(Capsule())
                }
            }

            if let price = offer.price {
                Text("Price: \(price)")
                    .font(.body)
                    .bold()
            }

            if let delivery = offer.delivery {
                Text(delivery)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            if let rating = offer.rating {
                if let reviews = offer.reviews {
                    Text(String(format: "Rating: %.1f (\(reviews) reviews)", rating))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } else {
                    Text(String(format: "Rating: %.1f", rating))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }

            if let link = offer.link, let url = URL(string: link) {
                Link("Open Offer", destination: url)
                    .font(.footnote)
            }
        }
        .padding()
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 18))
    }
}
