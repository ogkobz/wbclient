"""Выгрузка заказов за период в CSV.

Пример показывает обычный сценарий: длинная выгрузка, где лимиты
и обрыв связи — не исключение, а часть работы.

    python examples/export_orders.py 2026-09-01 orders.csv

Токен берётся из переменной окружения WB_TOKEN.
"""

from __future__ import annotations

import csv
import os
import sys

from wbclient import WBClient, WBError

FIELDS = [
    "date",
    "lastChangeDate",
    "srid",
    "nmId",
    "supplierArticle",
    "warehouseName",
    "regionName",
    "totalPrice",
    "discountPercent",
    "isCancel",
]


def fetch_orders(client: WBClient, date_from: str) -> list[dict]:
    """Забирает заказы постранично.

    WB отдаёт до 80 000 строк за раз и пагинирует по времени: следующий
    запрос начинается с lastChangeDate последней строки. Повтор границы —
    норма, поэтому дубли отсеиваем по srid.
    """
    seen: set[str] = set()
    rows: list[dict] = []
    cursor = date_from

    while True:
        batch = client.get(
            "statistics",
            "/api/v1/supplier/orders",
            params={"dateFrom": cursor, "flag": 0},
        )
        if not batch:
            break

        fresh = [row for row in batch if row.get("srid") not in seen]
        seen.update(row.get("srid") for row in fresh)
        rows.extend(fresh)
        print(f"  получено {len(batch)}, новых {len(fresh)}, всего {len(rows)}")

        if not fresh:
            break
        cursor = batch[-1]["lastChangeDate"]

    return rows


def main() -> int:
    token = os.environ.get("WB_TOKEN")
    if not token:
        print("Не задана переменная окружения WB_TOKEN", file=sys.stderr)
        return 1

    date_from = sys.argv[1] if len(sys.argv) > 1 else "2026-01-01"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "orders.csv"

    client = WBClient(token)
    if client.info is None:
        print("Токен не похож на JWT — проверьте, что скопировали его целиком.",
              file=sys.stderr)
        return 1
    if not client.info.allows("statistics"):
        print("У токена нет категории «Статистика». Создайте новый в кабинете.",
              file=sys.stderr)
        return 1

    try:
        rows = fetch_orders(client, date_from)
    except WBError as exc:
        print(f"WB вернул ошибку: {exc}", file=sys.stderr)
        return 1

    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Готово: {len(rows)} заказов в {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
