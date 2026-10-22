# CodeBoardingでMovie Modifyを可視化する

**ChatGPTがソースコードの構造を整理し、CodeBoardingは描画と探索に利用する方式です。** CodeBoarding側のLLM/CLI解析は実行しません。OpenAI APIキー、CodeBoardingのLLM設定、PythonのCodeBoardingパッケージの導入は**閲覧だけなら不要**です。

## すぐに見る

1. [CodeBoardingのMovie Modifyビュー](https://app.codeboarding.org/kameusagiyahoo/movie_modify)を開きます。公開リポジトリの `.codeboarding/analysis.json` を認識できれば、そのまま構成図が表示されます。
2. 表示されない場合は、[CodeBoarding Viewer](https://app.codeboarding.org/) を開き、**Switch source → File** でローカルJSONを選択します。
3. JSONは [.codeboarding/analysis.json](../.codeboarding/analysis.json) にあります。GitHubの**Raw（生データ）**からファイルとして保存して利用してください。
4. 全体図からブロックを選択し、各サブコンポーネントへ移動すると、関連ソースと行番号を確認できます。

## 表示するブロック

トップレベルは以下の8区分です。

1. Pages/Studioブラウザ編集
2. PC詳細エディター
3. FastAPI・プロジェクト管理
4. 編集データ（EDL）・幾何
5. FFmpeg/FFprobeメディア処理
6. 360度人物追尾
7. Pages→PC転送・同期
8. 追尾の定量評価

階層化した**20個の下位ブロック**に分解し、全体とサブシステムの関係、ソース参照を収録しています。

## このJSONについての注意

- **生成者：ChatGPT**。公式のCodeBoarding CLIが言語サーバーやLLMで作成した分析ではありません。CodeBoardingの公開JSON構造（metadata、files、methods_index、components、components_relations）に合わせた互換形式です。
- **解析対象：主要17ファイル**。PythonとJavaScript/HTMLの実装を中心に整理しました。テスト、ドキュメント、CI、CSS等のすべてを関数単位で解析したわけではありません。
- **依存関係の意味：設計・実装に基づく説明的な線**。Python関数の実際の関係を優先しつつ、異なる言語をまたぐAPI連携なども記述しています。機械的な完全コールグラフとは異なるため `is_static:false` としてあります。動的呼び出しは漏れがあり得ます。
- **更新：手動**。今後コードに機能追加した場合、ChatGPTに同ファイルの更新を依頼してください。ソースと構成図が自動で常に同期するわけではありません。
- **プライバシー**：この図は公開GitHubリポジトリのコード構造です。元動画・個人データはJSONに含めません。公開ビューを利用すると公開GitHub上の分析情報をCodeBoardingが読み込む可能性があります。
- **表示互換**：公式の現在のサンプルスキーマに沿っていますが、CodeBoarding Webビューアでの手動操作・描画完了まではここで実機確認していません。もしCodeBoarding側が内部スキーマを変更した場合は調整が必要です。

本プロジェクトの実装・制約の正本は引き続き [統合仕様書](SPECIFICATION.md) です。このJSONは設計理解・レビュー用の補助資料です。
