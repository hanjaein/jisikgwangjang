# 사진 정리 (PhotoCleaner)

아이폰에서 사진을 한 장씩 넘겨보며 빠르게 정리하는 iOS 앱입니다.
화면 하단에는 **안하기** / **삭제하기** 두 개의 버튼만 있습니다.

- **안하기**: 현재 사진을 그대로 두고 다음 사진으로 넘어갑니다.
- **삭제하기**: 현재 사진을 삭제 목록에 담고 바로 다음 사진으로 넘어갑니다.

사진을 모두 넘기면 완료 화면에서 **삭제 실행** 버튼으로 담아 둔 사진을
한 번에 삭제합니다. (iOS 정책상 실제 삭제 시 시스템 확인창이 한 번 표시됩니다.)

## 특징

- SwiftUI + PhotoKit 로 구현
- 매번 확인창을 띄우지 않아 정리가 빠릅니다 (삭제는 마지막에 한 번에 실행)
- 세로 방향, 다크 모드 UI

## 실행 방법

1. macOS + Xcode 16 이상에서 `PhotoCleaner/PhotoCleaner.xcodeproj` 를 엽니다.
2. 상단에서 실행 대상을 실제 아이폰(또는 시뮬레이터)으로 선택합니다.
   - 시뮬레이터에는 기본 샘플 사진이 들어 있어 동작 확인이 가능합니다.
   - 실제 기기에서 실행하려면 프로젝트의 **Signing & Capabilities** 에서
     본인 Apple 개발자 팀을 선택하고, `PRODUCT_BUNDLE_IDENTIFIER` 를
     고유한 값(예: `com.yourname.PhotoCleaner`)으로 바꿔 주세요.
3. `⌘R` 로 실행한 뒤, 사진 접근을 허용하면 정리를 시작할 수 있습니다.

## 프로젝트 구조

```
PhotoCleaner/
├─ PhotoCleaner.xcodeproj
└─ PhotoCleaner/
   ├─ PhotoCleanerApp.swift      # 앱 진입점
   ├─ ContentView.swift          # 화면 UI (사진 + 하단 버튼)
   ├─ PhotoLibraryManager.swift  # 사진 접근/로드/삭제 로직
   └─ Assets.xcassets
```

## 사진 접근 권한 안내 문구

`Info.plist` 값은 빌드 설정(`INFOPLIST_KEY_*`)으로 자동 생성됩니다.

- `NSPhotoLibraryUsageDescription`: 사진 정리를 위해 사진 접근을 요청합니다.

## 참고

- 실제로 사진을 삭제하려면 실제 아이폰 기기에서 실행하는 것이 가장 정확합니다.
- 삭제된 사진은 iOS의 "최근 삭제된 항목" 앨범에 일정 기간 보관되므로
  실수로 지워도 복구할 수 있습니다.
