import Foundation
import Photos
import UIKit

/// 사진 라이브러리에 접근하고, 사진을 한 장씩 넘기거나 삭제 예약을 관리한다.
///
/// iOS 는 앱이 사진을 소리 없이 지우는 것을 허용하지 않는다. 그래서 "삭제하기" 를
/// 누르면 즉시 다음 사진으로 넘어가고, 지울 사진은 목록에 모아 두었다가 마지막에
/// 시스템 확인창을 통해 한 번에 삭제한다. (확인창을 매번 띄우지 않아 더 매끄럽다.)
@MainActor
final class PhotoLibraryManager: NSObject, ObservableObject {

    enum AuthState {
        case notDetermined
        case authorized
        case limited
        case denied
    }

    @Published private(set) var authState: AuthState = .notDetermined
    @Published private(set) var assets: [PHAsset] = []
    @Published private(set) var currentIndex: Int = 0

    /// 삭제 예약된 사진들 (아직 실제로 지워지지 않음)
    @Published private(set) var pendingDeletions: [PHAsset] = []

    /// 되돌리기(undo)를 위한 동작 기록
    enum Action { case skip, delete }
    private var history: [(index: Int, action: Action)] = []

    /// 되돌릴 수 있는 동작이 있는지
    @Published private(set) var canUndo: Bool = false

    /// 현재 사진의 표시용 이미지
    @Published var currentImage: UIImage?

    /// 모든 사진을 다 넘겼는지 여부
    @Published private(set) var isFinished: Bool = false

    private let imageManager = PHCachingImageManager()
    private var currentRequestID: PHImageRequestID?

    var totalCount: Int { assets.count }
    var pendingDeleteCount: Int { pendingDeletions.count }

    /// 현재 사진이 삭제 예약 상태인지
    var isCurrentPending: Bool {
        guard let asset = currentAsset else { return false }
        return pendingDeletions.contains { $0.localIdentifier == asset.localIdentifier }
    }

    var currentAsset: PHAsset? {
        guard assets.indices.contains(currentIndex) else { return nil }
        return assets[currentIndex]
    }

    // MARK: - 권한

    func requestAuthorization() {
        let status = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        applyStatus(status)

        guard status == .notDetermined else {
            if authState == .authorized || authState == .limited {
                loadAssets()
            }
            return
        }

        PHPhotoLibrary.requestAuthorization(for: .readWrite) { [weak self] newStatus in
            Task { @MainActor in
                guard let self else { return }
                self.applyStatus(newStatus)
                if self.authState == .authorized || self.authState == .limited {
                    self.loadAssets()
                }
            }
        }
    }

    private func applyStatus(_ status: PHAuthorizationStatus) {
        switch status {
        case .authorized:
            authState = .authorized
        case .limited:
            authState = .limited
        case .denied, .restricted:
            authState = .denied
        case .notDetermined:
            authState = .notDetermined
        @unknown default:
            authState = .denied
        }
    }

    // MARK: - 사진 로드

    func loadAssets() {
        let options = PHFetchOptions()
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        options.predicate = NSPredicate(format: "mediaType == %d", PHAssetMediaType.image.rawValue)

        let result = PHAsset.fetchAssets(with: options)
        var fetched: [PHAsset] = []
        fetched.reserveCapacity(result.count)
        result.enumerateObjects { asset, _, _ in
            fetched.append(asset)
        }

        assets = fetched
        currentIndex = 0
        pendingDeletions.removeAll()
        history.removeAll()
        canUndo = false
        isFinished = fetched.isEmpty
        loadCurrentImage()
    }

    // MARK: - 이미지

    func loadCurrentImage() {
        if let id = currentRequestID {
            imageManager.cancelImageRequest(id)
            currentRequestID = nil
        }

        guard let asset = currentAsset else {
            currentImage = nil
            return
        }

        let options = PHImageRequestOptions()
        options.isNetworkAccessAllowed = true
        options.deliveryMode = .opportunistic
        options.resizeMode = .fast

        let scale = UIScreen.main.scale
        let target = CGSize(width: UIScreen.main.bounds.width * scale,
                            height: UIScreen.main.bounds.height * scale)

        currentRequestID = imageManager.requestImage(
            for: asset,
            targetSize: target,
            contentMode: .aspectFit,
            options: options
        ) { [weak self] image, _ in
            guard let self, let image else { return }
            Task { @MainActor in
                self.currentImage = image
            }
        }
    }

    // MARK: - 넘기기 / 삭제 예약

    /// "안하기" — 현재 사진을 그대로 두고 다음으로 넘어간다.
    func skip() {
        guard currentAsset != nil else { return }
        history.append((index: currentIndex, action: .skip))
        canUndo = true
        advance()
    }

    /// "삭제하기" — 현재 사진을 삭제 목록에 넣고 다음으로 넘어간다.
    func markForDeletion() {
        guard let asset = currentAsset else { return }
        if !pendingDeletions.contains(where: { $0.localIdentifier == asset.localIdentifier }) {
            pendingDeletions.append(asset)
        }
        history.append((index: currentIndex, action: .delete))
        canUndo = true
        advance()
    }

    /// "되돌리기" — 마지막 동작(안하기/삭제하기)을 취소하고 이전 사진으로 돌아간다.
    func undo() {
        guard let last = history.popLast() else { return }

        if last.action == .delete, assets.indices.contains(last.index) {
            let asset = assets[last.index]
            pendingDeletions.removeAll { $0.localIdentifier == asset.localIdentifier }
        }

        currentIndex = last.index
        isFinished = false
        canUndo = !history.isEmpty
        loadCurrentImage()
    }

    private func advance() {
        if currentIndex + 1 < assets.count {
            currentIndex += 1
            loadCurrentImage()
        } else {
            currentIndex = assets.count
            currentImage = nil
            isFinished = true
        }
    }

    // MARK: - 실제 삭제 실행

    /// 삭제 예약된 사진들을 실제로 지운다. 시스템 확인창이 한 번 뜬다.
    func commitDeletions() async -> Bool {
        guard !pendingDeletions.isEmpty else { return true }
        let toDelete = pendingDeletions

        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.deleteAssets(toDelete as NSArray)
            }
            pendingDeletions.removeAll()
            return true
        } catch {
            // 사용자가 확인창에서 취소한 경우 등
            return false
        }
    }

    /// 처음부터 다시 정리한다.
    func restart() {
        loadAssets()
    }
}
