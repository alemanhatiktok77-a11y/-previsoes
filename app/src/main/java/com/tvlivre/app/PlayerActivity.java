package com.tvlivre.app;

import android.app.Activity;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.GestureDetector;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;

import androidx.media3.common.MediaItem;
import androidx.media3.common.MimeTypes;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;
import androidx.media3.ui.PlayerView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashMap;
import java.util.Map;

/**
 * Reprodutor em tela cheia (ExoPlayer/Media3): HLS, DASH, MPEG-TS e arquivos progressivos.
 * Troca de canal: ▲▼ no controle remoto, botões CH+/CH-, ou deslizando o dedo para cima/baixo.
 */
public class PlayerActivity extends Activity {
    static String pending;
    private ExoPlayer player;
    private PlayerView view;
    private TextView info;
    private JSONArray list = new JSONArray();
    private int index;
    private boolean triedHls;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable hideInfo = () -> info.setVisibility(View.GONE);
    private GestureDetector gestures;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        view = new PlayerView(this);
        view.setShowBuffering(PlayerView.SHOW_BUFFERING_ALWAYS);
        view.setKeepScreenOn(true);
        root.addView(view, new FrameLayout.LayoutParams(-1, -1));
        info = new TextView(this);
        info.setTextColor(Color.WHITE);
        info.setTextSize(22);
        info.setBackgroundColor(0xCC0B5D3B);
        info.setPadding(36, 20, 36, 20);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.START);
        lp.setMargins(40, 40, 40, 40);
        root.addView(info, lp);
        setContentView(root);
        hideBars();

        try {
            list = new JSONArray(pending == null ? "[]" : pending);
        } catch (Exception e) {
            list = new JSONArray();
        }
        index = getIntent().getIntExtra("index", 0);

        player = new ExoPlayer.Builder(this).build();
        view.setPlayer(player);
        player.addListener(new Player.Listener() {
            @Override
            public void onPlayerError(PlaybackException error) {
                // sem extensão .m3u8, o ExoPlayer pode não reconhecer o HLS: tenta uma segunda vez como HLS
                if (!triedHls) {
                    triedHls = true;
                    start(true);
                    return;
                }
                showInfo("⚠ Canal indisponível agora: " + name() + "\n(fora do ar ou bloqueado na sua região)\n▲▼ ou deslize para trocar de canal", 8000);
            }

            @Override
            public void onPlaybackStateChanged(int state) {
                if (state == Player.STATE_READY) handler.postDelayed(hideInfo, 2500);
            }
        });
        gestures = new GestureDetector(this, new GestureDetector.SimpleOnGestureListener() {
            @Override
            public boolean onFling(MotionEvent e1, MotionEvent e2, float vx, float vy) {
                if (e1 == null || e2 == null) return false;
                float dy = e2.getY() - e1.getY();
                if (Math.abs(dy) > 150 && Math.abs(vy) > Math.abs(vx)) {
                    zap(dy < 0 ? 1 : -1);
                    return true;
                }
                return false;
            }
        });
        start(false);
    }

    private String name() {
        JSONObject c = list.optJSONObject(index);
        return c == null ? "" : c.optString("name", "");
    }

    private void start(boolean forceHls) {
        JSONObject c = list.optJSONObject(index);
        if (c == null) {
            showInfo("Nenhum canal", 4000);
            return;
        }
        String url = c.optString("url", "");
        String ua = c.optString("ua", "");
        String ref = c.optString("ref", "");
        DefaultHttpDataSource.Factory http = new DefaultHttpDataSource.Factory()
                .setUserAgent(ua.isEmpty() ? MainActivity.UA : ua)
                .setAllowCrossProtocolRedirects(true)
                .setConnectTimeoutMs(15000)
                .setReadTimeoutMs(20000);
        if (!ref.isEmpty()) {
            Map<String, String> headers = new HashMap<>();
            headers.put("Referer", ref);
            http.setDefaultRequestProperties(headers);
        }
        MediaItem.Builder item = new MediaItem.Builder().setUri(Uri.parse(url));
        if (forceHls || url.toLowerCase().contains(".m3u8")) item.setMimeType(MimeTypes.APPLICATION_M3U8);
        else if (url.toLowerCase().contains(".mpd")) item.setMimeType(MimeTypes.APPLICATION_MPD);
        player.setMediaSource(new DefaultMediaSourceFactory(http).createMediaSource(item.build()));
        player.prepare();
        player.setPlayWhenReady(true);
        showInfo((index + 1) + " / " + list.length() + "   " + name() + (c.optString("group").isEmpty() ? "" : "\n" + c.optString("group")), 0);
    }

    private void zap(int dir) {
        if (list.length() == 0) return;
        index = (index + dir + list.length()) % list.length();
        triedHls = false;
        start(false);
    }

    private void showInfo(String text, int ms) {
        handler.removeCallbacks(hideInfo);
        info.setText(text);
        info.setVisibility(View.VISIBLE);
        if (ms > 0) handler.postDelayed(hideInfo, ms);
    }

    private void hideBars() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent ev) {
        if (gestures != null && gestures.onTouchEvent(ev)) return true;
        return super.dispatchTouchEvent(ev);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP:
            case KeyEvent.KEYCODE_CHANNEL_UP:
            case KeyEvent.KEYCODE_PAGE_UP:
                zap(-1);
                return true;
            case KeyEvent.KEYCODE_DPAD_DOWN:
            case KeyEvent.KEYCODE_CHANNEL_DOWN:
            case KeyEvent.KEYCODE_PAGE_DOWN:
                zap(1);
                return true;
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_INFO:
                showInfo((index + 1) + " / " + list.length() + "   " + name(), 3000);
                view.showController();
                return true;
            default:
                return super.onKeyDown(keyCode, event);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideBars();
        if (player != null) player.setPlayWhenReady(true);
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (player != null) player.setPlayWhenReady(false);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        handler.removeCallbacksAndMessages(null);
        if (player != null) {
            player.release();
            player = null;
        }
    }
}
