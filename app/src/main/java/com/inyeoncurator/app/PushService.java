package com.inyeoncurator.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/**
 * 푸시 알림 받기 (FCM). 서버(send-push)는 data 메시지로 보내고, 알림은 여기서 직접 만든다.
 * 앱을 보고 있을 때는 웹 화면이 알림 배너를 띄우므로 표시줄 알림은 만들지 않는다.
 */
public class PushService extends FirebaseMessagingService {

    static final String CHANNEL = "inyeon";
    static volatile boolean foreground = false;

    static void ensureChannel(Context c) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm.getNotificationChannel(CHANNEL) != null) return;
        NotificationChannel ch = new NotificationChannel(CHANNEL, "인연 알림", NotificationManager.IMPORTANCE_HIGH);
        ch.setDescription("대화 신청, 새 메시지, 꽃 같은 알림");
        nm.createNotificationChannel(ch);
    }

    @Override
    public void onNewToken(@NonNull String token) {
        // 앱이 켜져 있으면 웹에 바로 알려 서버에 다시 등록하게 함 (꺼져 있으면 다음 실행 때 등록)
        MainActivity a = MainActivity.current;
        if (a != null) a.runOnUiThread(() -> a.pushTokenChanged(token));
    }

    @Override
    public void onMessageReceived(@NonNull RemoteMessage msg) {
        if (foreground) return;
        Map<String, String> d = msg.getData();
        String title = d.get("title"), body = d.get("body");
        if (title == null && msg.getNotification() != null) { title = msg.getNotification().getTitle(); body = msg.getNotification().getBody(); }
        if (title == null) return;
        ensureChannel(this);

        Intent open = new Intent(this, MainActivity.class)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra("push_kind", d.containsKey("kind") ? d.get("kind") : "")
                .putExtra("push_ref", d.containsKey("ref") ? d.get("ref") : "");
        int nid = (int) (System.currentTimeMillis() % Integer.MAX_VALUE);
        PendingIntent pi = PendingIntent.getActivity(this, nid, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder b = new NotificationCompat.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_notify)
                .setColor(0xFFD9B46A)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(pi);
        String group = d.get("group");
        if (group != null) b.setGroup(group);
        try { NotificationManagerCompat.from(this).notify(nid, b.build()); } catch (SecurityException ignored) { /* 알림 권한 꺼짐 */ }
    }
}
