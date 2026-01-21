//
//  AppState.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//

import Foundation
import UIKit
import Combine

@MainActor
final class AppState: ObservableObject {
    @Published var selectedImage: UIImage?
    @Published var identifyResponse: IdentifyResponse?
    @Published var selectedCandidate: ProductCandidate?
    @Published var offersResponse: OffersResponse?
    @Published var includeMembershipStores: Bool = true
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?

    // ✅ fixed
    let api = APIClient()
}
