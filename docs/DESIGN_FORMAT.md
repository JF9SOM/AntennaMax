# design.yaml の形式

`antennamax run design.yaml` が読み込む設計ファイル。UTF-8 で保存すること。
未知のキーはエラーになる(タイプミス検出のため)。例は `examples/` を参照。

```yaml
template: yagi            # dipole | yagi
params:                   # テンプレートのパラメータ(下記)
  center_frequency_mhz: 144
  ...
sweep:
  start_mhz: 142
  stop_mhz: 146
  points: 5
pattern:                  # 省略すると放射パターンは計算しない
  resolution_deg: 10
```

## 単位表記

内部は SI(m, Hz)。値は `*_mm`(→ `*_m`)、`*_mhz`(→ `*_hz`)の別名でも書ける。
同じ量を複数の単位で書くとエラー。`params` の中でも、`sweep` でも同じ規則。

## template / params

### dipole(自由空間、素子は y 軸方向)
| キー | 内容 |
|---|---|
| `center_frequency_hz` / `_mhz` | 中心周波数(必須) |
| `length_m` / `_mm` | 全長。省略時は 0.95 × λ/2(目安。VERIFICATION.md 参照) |
| `diameter_m` / `_mm` | 導体径(必須) |
| `segments` | 分割数。奇数。省略時は自動決定(下記)。指定時はそのまま使い、細線近似の警告のみ |

### yagi(自由空間、素子は y 軸に平行、ブームは x 軸)
| キー | 内容 |
|---|---|
| `center_frequency_hz` / `_mhz` | 分割数決定に使う中心周波数(必須) |
| `elements` | 2 個以上のリスト。各要素: `position_m`/`_mm`(ブーム上の位置)、`length_m`/`_mm`(全長)、`diameter_m`/`_mm`(導体径) |
| `feed_index` | 給電エレメントの番号(0 始まり) |
| `segments_per_wavelength` | 波長あたりの目標分割数(既定 20)。全エレメント同一分割数 |

反射器から導波器の順に `position` を増やして並べる(主ビームは +x 方向)。
ブーム補正は未実装。

### qfh(四線ヘリカル、自由空間、軸は z、給電は上部)
| キー | 内容 |
|---|---|
| `center_frequency_hz` / `_mhz` | 周波数(必須) |
| `diameter_m` / `_mm` | 導体径(必須。補正係数は 15 mm で頭打ち) |
| `bend_radius_m` / `_mm` | 曲げ半径(必須。寸法計算のみ。NEC2 形状は直角) |
| `turns` | 巻き数(既定 0.5) |
| `width_height_ratio` | 幅/高さ比(既定 0.44) |
| `handedness` | `left`(既定、給電点が上で天頂向きに RHCP)または `right`(LHCP) |
| `speed_of_light_m_s` | 光速(既定 299792458。Coppens の原典に合わせるなら 3e8) |
| `segments_per_wavelength` / `max_frequency_*` | 分割数の自動決定(dipole と同じ) |

寸法式は Coppens (ON6JC) の方式を KF8EEZ が再実装したページに準拠(出典と未照合の点は
`templates/qfh.py` と VERIFICATION.md を参照)。大ループ・小ループの全長、補正後全長、D、Dc、
H、垂直部長は `Qfh.dimensions` で取得できる。

### 分割数の自動決定

`segments` を省略した dipole と、yagi は `core/segmentation.py` で分割数を決める。
最高周波数(掃引の上限。`max_frequency_hz`/`_mhz` を params で指定すれば優先)で評価する。

- 制約: セグメント長 < λ/10、かつ セグメント長/半径 Δ/a > 2(NEC2 拡張細線カーネルの下限)
- 目標密度(`segments_per_wavelength`)から N を決め、Δ/a の制約で上限を超えれば N を減らし、
  λ/10 で足りなければ N を増やす。中央給電のため奇数。yagi は全エレメント同一 N
  (最も厳しいエレメントで決める)
- 両立できない場合(例: 1296 MHz で直径 30 mm のエレメント)はエラー
  (`cannot segment this geometry for NEC2 ...`、終了コード 2)
- Δ/a < 8 になるときは拡張細線カーネルが自動で有効になる

## sweep

`start_*`、`stop_*`(MHz または Hz)、`points`(点数)。周波数は等間隔。
`points: 1` なら `start` の 1 点。`stop` は `start` 以上。

## pattern

`resolution_deg`: 角度分解能(deg)。180 と 360 を割り切る値のみ(例: 5, 10, 15, 30)。
θ は 0〜180°(両端含む)、φ は 0〜360° 未満。

## 出力

- 既定: ソルバー情報の行(拡張細線カーネルの on/off と最小 Δ/a)と、周波数ごとの R, X, SWR(Z0 = 50 Ω)の表。パターン計算時は最大利得、F/B(dB)、天頂(θ=0)の軸比 AR と RHCP/LHCP 利得(dBic)も表示。
  AR は円偏波 0 dB、直線偏波は inf(JSON では null)。
- `impedance`/`swr` は最初の給電点基準。給電点が複数のとき(Geometry の `feeds`)は
  `feed_impedances_*`(周波数×給電数)に全給電点が入り、表には注記が 1 行出る。
- `--json`: `{"template": ..., "result": {...}}`。`result` のキーは
  `frequencies_hz, z0, impedance_real, impedance_imag, feed_impedances_real,
  feed_impedances_imag, swr, theta_rad, phi_rad, gain_dbi,
  max_gain_dbi, front_to_back_db, zenith_axial_ratio_db, zenith_rhcp_gain_dbic,
  zenith_lhcp_gain_dbic, meta`(パターン未計算の項目は null)。`meta` はソルバー情報で、
  `solver`("nec2")、`extended_kernel`(拡張細線カーネルの使用有無)、
  `min_segment_to_radius`(全 Wire の最小 Δ/a)を含む。
  JSON は無限大を表せないため、SWR 無限大・完全ヌル(-inf)・F/B 無限大・AR 無限大・利得 -inf は
  `null` で出力する。
- 設計ファイルのエラーは標準エラー出力にメッセージを出し、終了コード 2 を返す。
- 細線近似の適用条件(セグメント長/半径 Δ/a < 8)を外れる Wire があると、標準エラー出力に
  `antennamax: warning: ...` を出す(Δ/a < 2 は拡張カーネルでも範囲外の強い警告)。
  `view` ではその Wire を黄色(Δ/a < 8)・赤(Δ/a < 2)で表示する。
