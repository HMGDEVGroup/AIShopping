//
//  AIShoppingApp.swift
//  AIShopping
//
//  Created by Patrick on 1/20/26.
//

import SwiftUI

@main
struct AIShoppingApp: App {
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                UploadView()
            }
            .environmentObject(state)
        }
    }
}
