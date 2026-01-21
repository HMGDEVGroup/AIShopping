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
        VStack(alignment: .leading, spacing: 6) {

            HStack {
                Text(offer.source ?? "Unknown seller")
                    .bold()

                Spacer()

                if isBest {
                    Text("BEST")
                        .bold()
                        .foregroundStyle(.green)
                }
            }

            Text(offer.title)
                .font(.subheadline)

            HStack {
                Text(offer.price ?? "—")
                Spacer()
                if let delivery = offer.delivery, !delivery.isEmpty {
                    Text(delivery)
                        .foregroundStyle(.secondary)
                }
            }
            .font(.footnote)

            if let link = offer.link, let url = URL(string: link) {
                Link("Open Deal", destination: url)
                    .font(.subheadline)
            }
        }
        .padding(.vertical, 6)
    }
}
