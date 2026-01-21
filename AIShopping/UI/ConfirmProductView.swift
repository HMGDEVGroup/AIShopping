//
//  ConfirmProductView.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.

import SwiftUI

struct ConfirmProductView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Confirm Product")
                .font(.title2)
                .bold()

            if let res = state.identifyResponse {
                List {
                    Section("Primary") {
                        candidateRow(res.primary)
                    }

                    Section("Other matches") {
                        ForEach(res.candidates) { c in
                            candidateRow(c)
                        }
                    }
                }
            } else {
                Text("No product identified yet.")
            }

            Button("Find Best Prices") {
                Task { await fetchOffers() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(state.selectedCandidate == nil || state.isLoading)

            if state.isLoading {
                ProgressView()
            }

            if let err = state.errorMessage {
                Text(err)
                    .foregroundStyle(.red)
            }

            NavigationLink("View Results", destination: ResultsView())
                .disabled(state.offersResponse == nil)
        }
        .padding()
    }

    @ViewBuilder
    private func candidateRow(_ c: ProductCandidate) -> some View {
        HStack {
            VStack(alignment: .leading) {
                Text("\(c.brand ?? "") \(c.name)")
                    .bold()

                Text("Model: \(c.model ?? "—") • UPC: \(c.upc ?? "—")")
                    .font(.footnote)

                Text("Confidence: \(String(format: "%.2f", c.confidence))")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Image(systemName: (state.selectedCandidate?.id == c.id) ? "checkmark.circle.fill" : "circle")
        }
        .contentShape(Rectangle())
        .onTapGesture {
            state.selectedCandidate = c
        }
    }

    private func fetchOffers() async {
        guard let c = state.selectedCandidate else { return }

        state.isLoading = true
        state.errorMessage = nil

        do {
            let offers = try await state.api.offers(
                canonicalQuery: c.canonical_query,
                includeMembership: state.includeMembershipStores
            )
            state.offersResponse = offers
        } catch {
            state.errorMessage = "Offers failed: \(error.localizedDescription)"
        }

        state.isLoading = false
    }
}
