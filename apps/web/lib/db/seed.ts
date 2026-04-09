/**
 * 競艇場マスタのシードデータ
 * 実行: DATABASE_URL=xxx npx tsx lib/db/seed.ts
 */
import { db } from "./index";
import { stadiums } from "./schema";

const STADIUMS = [
  { id: 1,  name: "桐生",   location: "群馬県", waterType: "淡水", inWinRate: 0.551 },
  { id: 2,  name: "戸田",   location: "埼玉県", waterType: "淡水", inWinRate: 0.551 },
  { id: 3,  name: "江戸川", location: "東京都", waterType: "海水", inWinRate: 0.437 },
  { id: 4,  name: "平和島", location: "東京都", waterType: "海水", inWinRate: 0.523 },
  { id: 5,  name: "多摩川", location: "東京都", waterType: "淡水", inWinRate: 0.568 },
  { id: 6,  name: "浜名湖", location: "静岡県", waterType: "海水", inWinRate: 0.545 },
  { id: 7,  name: "蒲郡",   location: "愛知県", waterType: "海水", inWinRate: 0.558 },
  { id: 8,  name: "常滑",   location: "愛知県", waterType: "海水", inWinRate: 0.580 },
  { id: 9,  name: "津",     location: "三重県", waterType: "海水", inWinRate: 0.600 },
  { id: 10, name: "三国",   location: "福井県", waterType: "海水", inWinRate: 0.565 },
  { id: 11, name: "びわこ", location: "滋賀県", waterType: "淡水", inWinRate: 0.535 },
  { id: 12, name: "住之江", location: "大阪府", waterType: "淡水", inWinRate: 0.570 },
  { id: 13, name: "尼崎",   location: "兵庫県", waterType: "海水", inWinRate: 0.689 },
  { id: 14, name: "鳴門",   location: "徳島県", waterType: "海水", inWinRate: 0.558 },
  { id: 15, name: "丸亀",   location: "香川県", waterType: "海水", inWinRate: 0.556 },
  { id: 16, name: "児島",   location: "岡山県", waterType: "海水", inWinRate: 0.566 },
  { id: 17, name: "宮島",   location: "広島県", waterType: "海水", inWinRate: 0.561 },
  { id: 18, name: "徳山",   location: "山口県", waterType: "海水", inWinRate: 0.577 },
  { id: 19, name: "下関",   location: "山口県", waterType: "海水", inWinRate: 0.590 },
  { id: 20, name: "若松",   location: "福岡県", waterType: "海水", inWinRate: 0.568 },
  { id: 21, name: "芦屋",   location: "福岡県", waterType: "海水", inWinRate: 0.562 },
  { id: 22, name: "福岡",   location: "福岡県", waterType: "海水", inWinRate: 0.574 },
  { id: 23, name: "唐津",   location: "佐賀県", waterType: "海水", inWinRate: 0.562 },
  { id: 24, name: "大村",   location: "長崎県", waterType: "海水", inWinRate: 0.683 },
];

async function main() {
  console.log("Seeding stadiums...");
  await db.insert(stadiums).values(STADIUMS).onConflictDoNothing();
  console.log(`Seeded ${STADIUMS.length} stadiums.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
