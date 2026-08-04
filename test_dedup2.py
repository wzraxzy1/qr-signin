import sqlite3

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("CREATE TABLE signins (id TEXT, session_id TEXT, field_data TEXT)")
SID = "s1"

def insert(rec):
    cur.execute("INSERT INTO signins (id, session_id, field_data) VALUES (?,?,?)",
                (rec["id"], SID, __import__("json").dumps(rec["data"], ensure_ascii=False)))

# Seed: 张伟 工号 E001 手机 138 身份证 110 学号 S001
insert({"id": "r1", "data": {"name": "张伟", "phone": "13800000000",
                              "employee_id": "E001", "id_card": "110", "student_number": "S001"}})

unique_fields = {"employee_id": "工号", "id_card": "身份证号", "student_number": "学号"}

def check(field_data):
    # composite rule (min) + per-field rule
    for uf in unique_fields:
        val = field_data.get(uf)
        if val is None or str(val).strip() == "":
            continue
        cur.execute(
            "SELECT id FROM signins WHERE session_id = ? AND json_extract(field_data, ?) = ?",
            (SID, f"$.{uf}", str(val)),
        )
        if cur.fetchone():
            return f"DUPLICATE({unique_fields[uf]})"
    return "OK"

cases = [
    # 同人 扫第二次（全部相同） -> 重复
    ({"name": "张伟", "phone": "13800000000", "employee_id": "E001", "id_card": "110", "student_number": "S001"}, "DUPLICATE"),
    # 不同人 但同工号 -> 重复（工号唯一）
    ({"name": "李雷", "phone": "13900000000", "employee_id": "E001", "id_card": "222", "student_number": "S002"}, "DUPLICATE"),
    # 不同人 同身份证不同工号 -> 重复（身份证唯一）
    ({"name": "韩梅梅", "phone": "13700000000", "employee_id": "E002", "id_card": "110", "student_number": "S003"}, "DUPLICATE"),
    # 不同人 同学号 -> 重复（学号唯一）
    ({"name": "王芳", "phone": "13600000000", "employee_id": "E003", "id_card": "333", "student_number": "S001"}, "DUPLICATE"),
    # 完全新的人 全部不同 -> 通过
    ({"name": "赵强", "phone": "13500000000", "employee_id": "E004", "id_card": "444", "student_number": "S004"}, "OK"),
    # 重名但工号/身份证/学号都不同 -> 通过（仅姓名相同不拦）
    ({"name": "张伟", "phone": "13811111111", "employee_id": "E005", "id_card": "555", "student_number": "S005"}, "OK"),
    # 仅填姓名（三个唯一字段都空）-> 通过（旧字段仍可签到）
    ({"name": "路人甲", "phone": "13400000000"}, "OK"),
]

all_ok = True
for i, (data, expect) in enumerate(cases, 1):
    got = check(data)
    status = "PASS" if got == expect else "FAIL"
    if status == "FAIL":
        all_ok = False
    print(f"case {i}: expect={expect} got={got} -> {status}")
    # 模拟写入（仅当通过）
    if got == "OK":
        insert({"id": f"new{i}", "data": data})

print("\nALL PASS" if all_ok else "\nSOME FAILED")
