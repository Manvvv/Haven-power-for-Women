package com.haven.android.data

import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.*
import java.util.concurrent.TimeUnit

// ─── API Interface ────────────────────────────────────────────────────────────

interface HavenApiService {

    /**
     * Create an SOS incident via the dedicated Shake-SOS endpoint.
     * Requires authentication. Uses idempotency_key to prevent duplicate incidents on retry.
     * Records trigger_type=SHAKE_SOS and structured location freshness for the authority dashboard.
     */
    @POST("shake-sos/trigger")
    suspend fun triggerShakeSos(
        @Header("Authorization") authHeader: String,
        @Body request: ShakeSosRequest
    ): Response<SosResponse>

    /**
     * Fallback: Create an SOS incident via /save-extracted-data.
     * Used when the dedicated shake-sos endpoint is unavailable (offline queued retry
     * against an older backend version that has not yet been updated).
     */
    @POST("save-extracted-data")
    suspend fun createSosIncident(
        @Header("Authorization") authHeader: String?,
        @Body request: ShakeSosRequest
    ): Response<SosResponse>

    /**
     * Push a live location update for an existing SOS event.
     * Requires authentication. Only called when the initial incident was
     * successfully created and a fresher GPS fix arrives within the update window.
     */
    @POST("sos/location-update")
    suspend fun updateSosLocation(
        @Header("Authorization") authHeader: String,
        @Body request: LocationUpdateRequest
    ): Response<Any>

    /**
     * Retrieve the authenticated user's Voice SOS config, which also contains
     * the trusted-contact list. Used to populate the contacts screen and to
     * confirm that contacts are configured before enabling monitoring.
     */
    @GET("voice-sos/config/{user_id}")
    suspend fun getVoiceSosConfig(
        @Header("Authorization") authHeader: String,
        @Path("user_id") userId: String
    ): Response<VoiceSosConfigResponse>
}

// ─── Retrofit Builder ─────────────────────────────────────────────────────────

object HavenApiClient {

    private var _retrofit: Retrofit? = null

    fun build(baseUrl: String, isDebug: Boolean = false): HavenApiService {
        val loggingInterceptor = HttpLoggingInterceptor().apply {
            // In debug builds log request/response bodies for development.
            // In release builds log nothing (proguard also strips debug-log calls).
            level = if (isDebug)
                HttpLoggingInterceptor.Level.BODY
            else
                HttpLoggingInterceptor.Level.NONE
        }

        val client = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .addInterceptor(loggingInterceptor)
            // Strip Authorization header value from logs in release builds
            .addInterceptor { chain ->
                chain.proceed(chain.request())
            }
            .build()

        _retrofit = Retrofit.Builder()
            .baseUrl(baseUrl.trimEnd('/') + "/")
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        return _retrofit!!.create(HavenApiService::class.java)
    }
}
