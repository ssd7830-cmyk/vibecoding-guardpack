"""회계 시스템으로 보낼 CSV를 표준 출력에 쓴다. loader의 amount(원)를 그대로 사용한다."""
import csv
import sys

from loader import load_rows


def main():
    writer = csv.writer(sys.stdout)
    writer.writerow(["name", "amount_won"])
    for row in load_rows():
        writer.writerow([row["name"], row["amount"]])


if __name__ == "__main__":
    main()
