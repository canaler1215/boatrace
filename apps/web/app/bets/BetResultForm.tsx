"use client";
import { useState } from "react";
import { updateBetResult } from "./actions";

export default function BetResultForm({ betId }: { betId: number }) {
  const [open, setOpen] = useState(false);
  const [isWin, setIsWin] = useState<boolean | null>(null);
  const [payout, setPayout] = useState("");
  const [saving, setSaving] = useState(false);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-blue-600 hover:underline"
      >
        結果入力
      </button>
    );
  }

  const handleSave = async () => {
    if (isWin === null) return;
    setSaving(true);
    try {
      await updateBetResult(betId, isWin, isWin ? parseInt(payout || "0", 10) : 0);
      setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1">
      <select
        value={isWin === null ? "" : isWin ? "win" : "lose"}
        onChange={(e) =>
          setIsWin(
            e.target.value === "win"
              ? true
              : e.target.value === "lose"
                ? false
                : null
          )
        }
        className="rounded border border-gray-300 px-2 py-1 text-xs"
      >
        <option value="">選択</option>
        <option value="win">的中</option>
        <option value="lose">外れ</option>
      </select>
      {isWin === true && (
        <input
          type="number"
          value={payout}
          onChange={(e) => setPayout(e.target.value)}
          placeholder="払戻額"
          min="0"
          className="w-24 rounded border border-gray-300 px-2 py-1 text-xs"
        />
      )}
      <button
        onClick={handleSave}
        disabled={isWin === null || saving}
        className="rounded bg-green-600 px-2 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
      >
        {saving ? "保存中…" : "保存"}
      </button>
      <button
        onClick={() => setOpen(false)}
        className="text-xs text-gray-400 hover:text-gray-600"
      >
        ×
      </button>
    </div>
  );
}
