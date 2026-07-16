import SwiftUI

struct ContentView: View {
    @StateObject private var manager = PhotoLibraryManager()

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            switch manager.authState {
            case .notDetermined:
                RequestAccessView { manager.requestAuthorization() }
            case .denied:
                DeniedView()
            case .authorized, .limited:
                contentBody
            }
        }
        .onAppear { manager.requestAuthorization() }
    }

    @ViewBuilder
    private var contentBody: some View {
        if manager.totalCount == 0 {
            EmptyLibraryView()
        } else if manager.isFinished {
            FinishedView(manager: manager)
        } else {
            SwipeView(manager: manager)
        }
    }
}

// MARK: - 사진 정리 화면

private struct SwipeView: View {
    @ObservedObject var manager: PhotoLibraryManager

    var body: some View {
        VStack(spacing: 0) {
            // 진행 상황
            HStack {
                Text("\(manager.currentIndex + 1) / \(manager.totalCount)")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white.opacity(0.85))
                Spacer()
                if manager.pendingDeleteCount > 0 {
                    Label("\(manager.pendingDeleteCount)장 삭제 예정", systemImage: "trash")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.red)
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)

            // 사진
            ZStack {
                if let image = manager.currentImage {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .id(manager.currentIndex)
                        .transition(.opacity)
                } else {
                    ProgressView()
                        .tint(.white)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.vertical, 16)
            .animation(.easeInOut(duration: 0.15), value: manager.currentIndex)

            // 하단 버튼: 안하기 / 삭제하기
            HStack(spacing: 16) {
                ActionButton(
                    title: "안하기",
                    systemImage: "arrow.right.circle.fill",
                    tint: .white,
                    background: Color.white.opacity(0.14)
                ) {
                    manager.skip()
                }

                ActionButton(
                    title: "삭제하기",
                    systemImage: "trash.fill",
                    tint: .white,
                    background: Color.red
                ) {
                    manager.markForDeletion()
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
    }
}

private struct ActionButton: View {
    let title: String
    let systemImage: String
    let tint: Color
    let background: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                Image(systemName: systemImage)
                    .font(.title2)
                Text(title)
                    .font(.headline)
            }
            .foregroundStyle(tint)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 18)
            .background(background)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
    }
}

// MARK: - 완료 화면

private struct FinishedView: View {
    @ObservedObject var manager: PhotoLibraryManager
    @State private var isDeleting = false
    @State private var didDelete = false
    @State private var deleteFailed = false

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: didDelete ? "checkmark.circle.fill" : "sparkles")
                .font(.system(size: 64))
                .foregroundStyle(didDelete ? .green : .yellow)

            if manager.pendingDeleteCount > 0 && !didDelete {
                Text("정리 완료!")
                    .font(.title.bold())
                    .foregroundStyle(.white)
                Text("\(manager.pendingDeleteCount)장을 삭제할 예정입니다.\n아래 버튼을 누르면 실제로 삭제됩니다.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white.opacity(0.8))

                Button {
                    Task {
                        isDeleting = true
                        deleteFailed = false
                        let ok = await manager.commitDeletions()
                        isDeleting = false
                        if ok { didDelete = true } else { deleteFailed = true }
                    }
                } label: {
                    HStack {
                        if isDeleting { ProgressView().tint(.white) }
                        Text(isDeleting ? "삭제 중..." : "삭제 실행")
                            .font(.headline)
                    }
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16)
                    .background(Color.red)
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .disabled(isDeleting)
                .padding(.horizontal, 32)

                if deleteFailed {
                    Text("삭제가 취소되었거나 실패했어요.")
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            } else {
                Text(didDelete ? "삭제 완료!" : "모두 확인했어요!")
                    .font(.title.bold())
                    .foregroundStyle(.white)
                Text("모든 사진을 정리했습니다.")
                    .foregroundStyle(.white.opacity(0.8))
            }

            Button {
                manager.restart()
            } label: {
                Text("처음부터 다시")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16)
                    .background(Color.white.opacity(0.14))
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .padding(.horizontal, 32)
        }
        .padding()
    }
}

// MARK: - 권한 / 빈 상태 화면

private struct RequestAccessView: View {
    let action: () -> Void
    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "photo.on.rectangle.angled")
                .font(.system(size: 64))
                .foregroundStyle(.white)
            Text("사진 정리")
                .font(.largeTitle.bold())
                .foregroundStyle(.white)
            Text("사진을 한 장씩 넘기면서 필요 없는 사진을 골라 삭제할 수 있어요.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.white.opacity(0.8))
                .padding(.horizontal, 32)
            Button(action: action) {
                Text("사진 접근 허용")
                    .font(.headline)
                    .foregroundStyle(.black)
                    .padding(.vertical, 16)
                    .frame(maxWidth: .infinity)
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .padding(.horizontal, 32)
        }
    }
}

private struct DeniedView: View {
    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "lock.fill")
                .font(.system(size: 56))
                .foregroundStyle(.white)
            Text("사진 접근이 필요해요")
                .font(.title2.bold())
                .foregroundStyle(.white)
            Text("설정 > 개인정보 보호 > 사진 에서\n이 앱의 사진 접근을 허용해 주세요.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.white.opacity(0.8))
            Button {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            } label: {
                Text("설정 열기")
                    .font(.headline)
                    .foregroundStyle(.black)
                    .padding(.vertical, 14)
                    .padding(.horizontal, 28)
                    .background(Color.white)
                    .clipShape(Capsule())
            }
        }
        .padding()
    }
}

private struct EmptyLibraryView: View {
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "photo")
                .font(.system(size: 56))
                .foregroundStyle(.white)
            Text("사진이 없어요")
                .font(.title2.bold())
                .foregroundStyle(.white)
            Text("정리할 사진이 없습니다.")
                .foregroundStyle(.white.opacity(0.8))
        }
    }
}

#Preview {
    ContentView()
}
