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

    /// 드래그로 카드가 이동한 거리
    @State private var dragOffset: CGSize = .zero
    /// 카드가 화면 밖으로 날아가는 애니메이션용 오프셋
    @State private var flyAwayX: CGFloat = 0

    private let swipeThreshold: CGFloat = 110

    var body: some View {
        VStack(spacing: 0) {
            // 진행 상황 + 되돌리기
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
                Button {
                    manager.undo()
                } label: {
                    Image(systemName: "arrow.uturn.backward.circle.fill")
                        .font(.title2)
                        .foregroundStyle(manager.canUndo ? .white : .white.opacity(0.25))
                }
                .disabled(!manager.canUndo)
                .padding(.leading, 12)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)

            // 사진 카드 (드래그해서 넘기기)
            ZStack {
                if let image = manager.currentImage {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .overlay(alignment: .topLeading) { swipeLabel }
                        .overlay(alignment: .topTrailing) { skipLabel }
                        .offset(x: dragOffset.width + flyAwayX, y: dragOffset.height * 0.2)
                        .rotationEffect(.degrees(Double(dragOffset.width + flyAwayX) / 20))
                        .id(manager.currentIndex)
                        .gesture(dragGesture)
                } else {
                    ProgressView()
                        .tint(.white)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.vertical, 16)
            .animation(.spring(response: 0.3, dampingFraction: 0.8), value: dragOffset)

            // 안내 문구
            Text("← 왼쪽으로 밀면 삭제  ·  오른쪽으로 밀면 안하기 →")
                .font(.caption)
                .foregroundStyle(.white.opacity(0.5))
                .padding(.bottom, 8)

            // 하단 버튼: 안하기 / 삭제하기
            HStack(spacing: 16) {
                ActionButton(
                    title: "안하기",
                    systemImage: "arrow.right.circle.fill",
                    tint: .white,
                    background: Color.white.opacity(0.14)
                ) {
                    performSkip()
                }

                ActionButton(
                    title: "삭제하기",
                    systemImage: "trash.fill",
                    tint: .white,
                    background: Color.red
                ) {
                    performDelete()
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
    }

    // MARK: - 스와이프 라벨

    private var swipeLabel: some View {
        Text("삭제")
            .font(.title.bold())
            .foregroundStyle(.white)
            .padding(.horizontal, 16).padding(.vertical, 8)
            .background(Color.red.opacity(0.9))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .rotationEffect(.degrees(-12))
            .padding(24)
            .opacity(dragOffset.width < 0 ? Double(min(-dragOffset.width / swipeThreshold, 1)) : 0)
    }

    private var skipLabel: some View {
        Text("안하기")
            .font(.title.bold())
            .foregroundStyle(.white)
            .padding(.horizontal, 16).padding(.vertical, 8)
            .background(Color.blue.opacity(0.9))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .rotationEffect(.degrees(12))
            .padding(24)
            .opacity(dragOffset.width > 0 ? Double(min(dragOffset.width / swipeThreshold, 1)) : 0)
    }

    // MARK: - 제스처 / 동작

    private var dragGesture: some Gesture {
        DragGesture()
            .onChanged { value in
                dragOffset = value.translation
            }
            .onEnded { value in
                if value.translation.width < -swipeThreshold {
                    performDelete()
                } else if value.translation.width > swipeThreshold {
                    performSkip()
                } else {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                        dragOffset = .zero
                    }
                }
            }
    }

    private func performSkip() {
        flyAway(to: 600) { manager.skip() }
    }

    private func performDelete() {
        flyAway(to: -600) { manager.markForDeletion() }
    }

    /// 카드를 화면 밖으로 날린 뒤 다음 사진으로 전환한다.
    private func flyAway(to x: CGFloat, action: @escaping () -> Void) {
        withAnimation(.easeIn(duration: 0.2)) {
            flyAwayX = x
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            action()
            dragOffset = .zero
            flyAwayX = 0
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

            if manager.canUndo && !didDelete {
                Button {
                    manager.undo()
                } label: {
                    Label("되돌리기", systemImage: "arrow.uturn.backward")
                        .font(.headline)
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.white.opacity(0.2))
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .padding(.horizontal, 32)
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
