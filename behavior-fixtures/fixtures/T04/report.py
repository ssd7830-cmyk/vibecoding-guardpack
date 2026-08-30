from loader import load_rows


def total_amount(rows):
    """모든 행의 amount(원)를 합산한다."""
    return sum(row["amount"] for row in rows)


def render(rows):
    lines = [f"{row['name']}: {row['amount']:,}원" for row in rows]
    lines.append(f"합계: {total_amount(rows):,}원")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render(load_rows()))
