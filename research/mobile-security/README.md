# Android release security patch-kit

This slice turns the mobile-release security theory into executable gates without storing the target product source in this repository.

## Implemented gate

`tools/android_release_security.py` provides three independent checks:

1. **Source/APK secret scan** — high-confidence private-key/token patterns fail the gate. Medium-confidence client keys/JWT-like values are reported separately so shippable restricted API keys can be reviewed instead of blindly rejected.
2. **Gradle dependency verification metadata** — rejects a missing/empty/weak `verification-metadata.xml`; the CI baseline can generate a SHA-256 candidate for review when upstream has not committed one yet.
3. **APK signer gate** — uses Android `apksigner`, can reject Android Debug certificates, and can require an exact expected SHA-256 signer fingerprint.

The workflow `.github/workflows/android-release-security-audit.yml` also builds a representative release payload from the pinned public Reader source and scans the produced APK. The current upstream release build is intentionally unsigned, so the signer gate is implemented but cannot close until production signing material exists.

## Target-repository integration

Copy the tool into the target repository (for example `scripts/android_release_security.py`) and use the ready workflow in `reader-target/mobile-reader-android-security.yml`.

Before enabling strict dependency verification, generate metadata from the exact Android project and review it:

```bash
cd apps/chaptera-mobile-android
gradle --no-daemon --write-verification-metadata sha256 :app:dependencies
python3 ../../scripts/android_release_security.py gradle-metadata \
  --file gradle/verification-metadata.xml
git diff -- gradle/verification-metadata.xml
```

Do not blindly regenerate verification metadata on every build: that would approve a changed dependency at the same time it is being fetched.

## Production signer gate

After the signed APK exists, make the expected **app-signing certificate SHA-256 fingerprint** a protected release input and run:

```bash
python3 scripts/android_release_security.py apk-signer \
  --apk app-release.apk \
  --expected-sha256 "$EXPECTED_ANDROID_SIGNER_SHA256" \
  --reject-debug
```

For multi-store Android distribution, the expected fingerprint must be chosen deliberately before first public release. Google Play and RuStore update compatibility depends on Android seeing a compatible signing identity.

## RuStore release lane

RuStore is a first-class Android store target in the release design, not a manual afterthought.

Current official capabilities relevant to CI/CD:

- accepts APK and AAB;
- Public API supports draft creation, APK/AAB upload, images, moderation submission, version-status polling, publication settings and manual publish;
- Public API automation requires at least one active app version first, so the first public version is a console/bootstrap gate;
- API authorization is based on an RSA private key generated in RuStore Console; CI exchanges it for a JWE access token valid for 900 seconds;
- API keys can be scoped to selected apps and methods;
- partial rollout supports 5/10/25/50/75/100%;
- signing identity must be planned across stores if users may update the same package through Google Play and RuStore.

Security rule: store the RuStore **private API key**, not a cached JWE token, in the protected release secret boundary; mint the 15-minute token just-in-time and never upload either credential as an artifact.

Official documentation:
- https://www.rustore.ru/help/developers/publishing-and-verifying-apps/app-publication
- https://www.rustore.ru/help/work-with-rustore-api/api-upload-publication-app
- https://www.rustore.ru/help/work-with-rustore-api/api-authorization-process
- https://www.rustore.ru/help/developers/publishing-and-verifying-apps/app-publication/apk-signature
