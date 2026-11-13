# 웹 화면과 연결되는 메서드는 이름이 바뀌면 안 됨
-keepclassmembers class com.inyeoncurator.app.Bridge {
    @android.webkit.JavascriptInterface <methods>;
}
