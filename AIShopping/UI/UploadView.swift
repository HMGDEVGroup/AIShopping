//
//  UploadView.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//

import SwiftUI
import PhotosUI

struct UploadView: View {
    @EnvironmentObject var state: AppState
    @State private var pickerItem: PhotosPickerItem?

    var body: some View {
        VStack(spacing: 16) {
            Text("AI Shopping")
                .font(.largeTitle).bold()

            Toggle("Include membership stores (Costco, etc.)", isOn: $state.includeMembershipStores)

            PhotosPicker("Upload a product photo or screenshot", selection: $pickerItem, matching: .images)
                .buttonStyle(.borderedProminent)

            if let img = state.selectedImage {
                Image(uiImage: img)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 300)
                    .cornerRadius(12)
            }

            Button("Identify Product") {
                Task { await identify() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(state.selectedImage == nil || state.isLoading)

            if state.isLoading { ProgressView() }
            if let err = state.errorMessage { Text(err).foregroundStyle(.red) }

            NavigationLink("Next", destination: ConfirmProductView())
                .disabled(state.identifyResponse == nil)
        }
        .padding()
        .onChange(of: pickerItem) { _, newItem in
            guard let newItem else { return }
            Task {
                if let data = try? await newItem.loadTransferable(type: Data.self),
                   let uiimg = UIImage(data: data) {
                    state.selectedImage = uiimg
                    state.identifyResponse = nil
                    state.selectedCandidate = nil
                    state.offersResponse = nil
                }
            }
        }
    }

    private func identify() async {
        guard let img = state.selectedImage else { return }
        state.isLoading = true
        state.errorMessage = nil
        do {
            let res = try await state.api.identify(image: img)
            state.identifyResponse = res
            state.selectedCandidate = res.primary
        } catch {
            state.errorMessage = "Identify failed: \(error.localizedDescription)"
        }
        state.isLoading = false
    }
}
