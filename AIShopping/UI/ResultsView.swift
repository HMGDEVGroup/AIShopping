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
            Text("Best Prices").font(.title2).bold()

            if let res = state.offersResponse {
                List {
                    ForEach(res.offers) { o in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(o.title).bold()
                            HStack {
                                Text(o.price ?? "—")
                                Spacer()
                                Text(o.source ?? "")
                                    .foregroundStyle(.secondary)
                            }
                            .font(.subheadline)

                            if let link = o.link, let url = URL(string: link) {
                                Link("Open Deal", destination: url)
                                    .font(.subheadline)
                            }
                        }
                        .padding(.vertical, 6)
                    }
                }
            } else {
                Text("No offers loaded yet.")
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
    }
}
