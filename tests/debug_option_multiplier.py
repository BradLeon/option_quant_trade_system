#!/usr/bin/env python3
"""Debug script to test fetching option contract multiplier from Futu API."""

from futu import OpenQuoteContext, RET_OK, SubType

# 测试期权代码 (Futu 格式)
TEST_OPTION_CODES = [
    "HK.ALB260129C160000",  # 阿里巴巴 Call
    "HK.TCH251230C600000",  # 腾讯 Call
    "HK.00700"
]


def main():
    quote_ctx = OpenQuoteContext(host="127.0.0.1", port=11111)

    try:
        print("=" * 60)
        print("Testing get_market_snapshot for option multiplier")
        print("=" * 60)

        # 先订阅
        print("\nSubscribing to option codes...")
        ret, data = quote_ctx.subscribe(TEST_OPTION_CODES, [SubType.ORDER_BOOK])
        if ret != RET_OK:
            print(f"Subscribe failed: {data}")
            return
        print("Subscribe OK")

        for code in TEST_OPTION_CODES:
            print(f"\n[{code}]")
            ret, data = quote_ctx.get_market_snapshot([code])

            if ret == RET_OK:
                print(f"Columns: {list(data.columns)}")

                # 打印关键字段
                if "option_contract_multiplier" in data.columns:
                    multiplier = data["option_contract_multiplier"].iloc[0]
                    print(f"  option_contract_multiplier: {multiplier}")
                else:
                    print("  option_contract_multiplier: NOT FOUND")

                if "option_valid" in data.columns:
                    print(f"  option_valid: {data['option_valid'].iloc[0]}")

                if "lot_size" in data.columns:
                    print(f"  lot_size: {data['lot_size'].iloc[0]}")

                # 打印所有 option 相关字段
                option_cols = [c for c in data.columns if "option" in c.lower()]
                print(f"  Option-related columns: {option_cols}")
                for col in option_cols:
                    print(f"    {col}: {data[col].iloc[0]}")
            else:
                print(f"  Error: {data}")

        print("\n" + "=" * 60)
        print("Test complete")
        print("=" * 60)

    finally:
        quote_ctx.close()


if __name__ == "__main__":
    main()
