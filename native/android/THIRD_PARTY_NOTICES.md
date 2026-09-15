# Android build and dependency notices

The Kotlin application and minimal OpenGL renderer in this directory were written for DishPlay. They do not copy the Google Hello AR sample's source code, assets, or shaders.

The committed Gradle wrapper scripts and JAR are unchanged files from [Gradle v8.11.1](https://github.com/gradle/gradle/tree/v8.11.1), distributed under the [Apache License 2.0](https://github.com/gradle/gradle/blob/v8.11.1/LICENSE). Their embedded copyright/license notices remain intact. The full license is included in `GRADLE_LICENSE`.

| Committed file | SHA-256 |
| --- | --- |
| `gradlew` | `9cbbb4d68ff7fb5211c4d58f598ac9d8664c05fdcd1e5f59b7f2c3ac1ee00af0` |
| `gradlew.bat` | `0f3ed8f03b50934cb8c48b15a470d5c20a30a5385825e48b55bcc8ea3d8f8e18` |
| `gradle/wrapper/gradle-wrapper.jar` | `2db75c40782f5e8ba1fc278a5574bab070adccb2d21ca5a6e5ed840888448046` |

The Gradle distribution checksum is pinned in `gradle-wrapper.properties`. Remote CI verifies the committed wrapper JAR before executing it.

Runtime/build dependencies remain governed by their own licenses: Android SDK, Google ARCore SDK / Google Play Services for AR, AndroidX Core, Android Gradle Plugin, Kotlin and Gradle. See [ARCore terms](https://developers.google.com/ar/develop/terms), [Android SDK terms](https://developer.android.com/studio/terms), and the resolved Maven artifacts' license metadata. This app does not provision any paid API, Cloud Anchor, GPU service, or subscription.
