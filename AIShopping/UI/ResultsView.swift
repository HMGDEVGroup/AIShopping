//
//  ResultsView.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//

import SwiftUI

struct ResultsView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Best Deals").font(.title2).bold()

            if let res = state.offersResponse {
                Text(res.explanation).font(.footnote).foregroundStyle(.secondary)

                List {
                    ForEach(Array(res.offers.enumerated()), id: \.element.id) { idx, offer in
                        OfferCard(offer: offer, isBest: idx == res.best_offer_index)
                    }
                }
            } else {
                Text("No offers loaded.")
            }
        }
        .padding()
    }
}
