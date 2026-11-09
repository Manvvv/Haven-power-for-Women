package com.haven.android.ui

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import com.haven.android.twa.TwaLauncherActivity

/**
 * MainActivity
 *
 * Primary responsibility: Forward any intent or legacy invocation immediately
 * to [TwaLauncherActivity] so the user always sees the production HAVEN website
 * (https://haven-your-own-voice.vercel.app/) as a Trusted Web Activity.
 *
 * The legacy native login screen and developer configuration panels are permanently
 * decoupled from the primary application launch experience.
 */
class MainActivity : ComponentActivity() {

    companion object {
        private const val TAG = "MainActivity"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "Forwarding launch intent to TwaLauncherActivity")

        val twaIntent = Intent(this, TwaLauncherActivity::class.java).apply {
            action = intent?.action
            data = intent?.data
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        startActivity(twaIntent)
        finish()
    }
}
