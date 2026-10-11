package br.cacau.radar;

import android.content.Context;
import android.content.pm.PackageInfo;

/** Nome da versão instalada (ex. 1.12), lido do próprio pacote. */
final class BuildConfigVersao {
    private BuildConfigVersao() {}

    static String nome(Context ctx) {
        try {
            PackageInfo info = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
            return info.versionName;
        } catch (Exception e) {
            return "?";
        }
    }
}
