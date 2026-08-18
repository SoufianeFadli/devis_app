# Devis SBBM pour Android

Cette application est une Trusted Web Activity (TWA) qui ouvre la version web
securisee de Devis SBBM en plein ecran. La version web reste disponible et les
deux versions utilisent le meme serveur et les memes donnees.

Version Android actuelle : `1.0.1` (`versionCode 2`).

## Compiler l'APK de test

1. Ouvrir le dossier `android` dans Android Studio, ou lancer `./gradlew assembleDebug`.
2. L'APK est genere dans `app/build/outputs/apk/debug/app-debug.apk`.

## Publication Google Play

1. Creer une cle de signature de production et la conserver hors du depot Git.
2. Configurer la signature `release` dans Gradle.
3. Generer un Android App Bundle avec `./gradlew bundleRelease`.
4. Ajouter l'empreinte SHA-256 fournie par Play App Signing dans la variable
   Render `ANDROID_CERT_SHA256`, puis redeployer le service web.

L'identifiant Android definitif est `ma.sbbm.devis`. Il ne doit pas changer
apres la premiere publication sur Google Play.
