# GitHub Pages ↔ Windows/Linux ローカル処理（同一UI）

Movie Modify には、PCなしで開ける **GitHub Pagesブラウザ版** と、
FFmpeg・OpenCV・Auto-Editorが使える **Windows/Linuxローカル版** があります。

## なぜPagesからPCを直接操作しないのか

GitHub PagesはHTTPS、家庭内PCは通常HTTPです。ブラウザは混在コンテンツや
プライベートネットワークへのリクエストを制限します。LAN上のHTTP APIへ
CORSを緩めて直接接続する方式は、安定性・安全性の両面で避けました。

代わりに、**同じブラウザ編集UIをローカルPCが /studio/ から配信**します。
ローカル編集画面とAPIが同一オリジン（同じホスト・ポート）になるため、
特別なCORS設定も外部サーバーも必要ありません。

## Pagesで編集した内容をPCへ引き継ぐ

1. [Pages版](https://kameusagiyahoo.github.io/movie_modify/)で動画を開いて編集する。
2. 「保存・出力」→「PCの高機能エンジン」で **編集JSONを保存して引き継ぐ**。
3. WindowsかLinuxのPCでサーバーを起動する（後述）。
4. Pagesの「PCのアドレス」にPCのIPを入力し、**ローカル編集画面を開く**。
5. ローカルの \`/studio/\` で同じ元動画と、保存したJSONを読み込む。
6. **動画と編集をPCに同期** を押す。元動画をPCに転送するか確認される。
7. **PCで高画質MP4を生成** でFFmpegを実行して動画をダウンロードできる。

手順4は**画面遷移**であって、GitHub PagesからローカルAPIへのバックグラウンド接続では
ありません。ブラウザが保持する元動画ファイルはセキュリティ上自動で引き継げないため、
手順5のファイル再選択が必要です。JSONを保存する前にページを離れないでください。

## ローカル版でできること

ローカル \`/studio/\` はPagesと同じ編集画面に「PCエンジン」操作が追加されたモードです。

- **動画と編集をPCに同期**：元動画を一度送信、次回以降は編集JSONを更新。転送前に確認ダイアログが出る。
- **PCで高画質MP4を生成**：FFmpegで720pまたは1080pのMP4を作成。
- **人物追尾・自動カットの詳細編集**：既存のローカル編集画面（\`/\`）で同じプロジェクトを開く。
- **PC側の編集結果をこの画面に取得**：詳細編集で保存したカット・画角・追尾を読み戻す。

同じプロジェクトをPC詳細画面とStudioで並行して変更した場合は、検出できる編集競合を
警告します。**同時編集に対する完全な競合解決は未実装**なので、
一方で保存し、もう一方で「PC側の編集結果を取得」してから続行してください。

## 起動

Windows PowerShell（準備がまだならFFmpeg・Python 3.11+をインストール）:

    .\scripts\start-windows.cmd

Linux:

    bash scripts/start-linux.sh

PC自身のブラウザから:

- http://127.0.0.1:8000/studio/ … Pagesと同じ画面＋PCエンジン
- http://127.0.0.1:8000/ … 従来のローカル詳細編集

iPhoneを同じプライベートWi-Fiで使う場合は、
\`MOVIE_MODIFY_TOKEN\` を設定した上で \`--lan\` をつけて起動します。

Windows PowerShell:

    $env:MOVIE_MODIFY_TOKEN="自分で設定した長いランダムな文字列"
    .\scripts\start-windows.cmd --lan

Linux:

    export MOVIE_MODIFY_TOKEN="自分で設定した長いランダムな文字列"
    bash scripts/start-linux.sh --lan

PCのLAN IPを調べ、iPhoneのSafariから \`http://PCのIP:8000/studio/\` を開きます。
初回のバックエンド操作時はトークンの入力を求められます。

**HTTP通信は暗号化されません。** 家庭内LANであっても機密性が必要ならHTTPS・
信頼できるVPNを利用してください。ルーターのポート開放は禁止。
GitHub Pages上にAPIパスワード、元動画、個人情報を埋め込まないでください。

## 制限

- Pagesで開いた動画は、ユーザーが明示的に「同期」を押すまでPCに送信されません。
- 重い8Kの元動画をiPhoneからPCへ送信するには時間・容量が必要です。
- 同一ネットワーク外では、そのままではPCへアクセスできません。
- PagesのWebGLプレビューはスマホ・ブラウザの性能に依存します。
- ローカルPCで作成した編集プロジェクトは、GitHub Pagesに自動アップロードされません。
- 人物の自動追尾は指定物体の外観を追う方式で、顔の本人識別ではありません。
