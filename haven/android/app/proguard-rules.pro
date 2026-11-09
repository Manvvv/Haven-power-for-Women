# ProGuard rules for HAVEN Android app

# Keep Retrofit models
-keepattributes Signature
-keepattributes *Annotation*
-keep class com.haven.android.data.** { *; }
-keep class com.haven.android.repository.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }

# Retrofit
-dontwarn retrofit2.**
-keep class retrofit2.** { *; }

# Gson
-keepattributes Signature
-keep class com.google.gson.** { *; }

# WorkManager
-keep class androidx.work.** { *; }
-keep class com.haven.android.service.PendingIncidentWorker { *; }

# Security — never log token values in release
-assumenosideeffects class android.util.Log {
    public static *** d(...);
    public static *** v(...);
}
