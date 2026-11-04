from pydantic import BaseModel, ConfigDict

"""
# 字典和对象的区别：

白话：
    字典 = 一张纸条，写着一堆【名字：值】，你靠引号里的名字拿东西
    对象 = 一个带标签的小盒子，盒子身上自带一堆按钮 / 属性，你靠点 `.` 拿东西

### 字典 dict

```
lab_dict = {"id": 1, "name": "一号实验室"}
print(lab_dict["name"])  # 用方括号 + 字符串名字去取
```

纸条规则：
    - 取东西：`["键名"]`
    - 键是字符串，写在引号里
    - 就是一堆平铺的键值对，没有别的功能

### 对象（比如 SQLAlchemy 查询出来的 ORM 对象）

```
lab_obj.id = 1
lab_obj.name = "一号实验室"
print(lab_obj.name)  # 用点 . 直接拿
```

盒子规则：
    - 取东西：`.属性名`
    - 不用引号，直接点名字
    - 除了存数据，还能附带函数、内部状态

回到刚才那句配置：
    Pydantic 默认只看得懂纸条（字典）。
    `from_attributes=True` 就是告诉它：**顺便也学会看懂盒子，支持用 `.` 读属性拿数据**。

一句话总结：
    - 字典：`xxx["名字"]`
    - 对象：`xxx.名字`

---

`model_config = ConfigDict(from_attributes=True)`

翻译成大白话：

QLAlchemy 查出来的东西，是一个 对象（像一个装好数据的盒子），不是字典。
正常情况下 Pydantic 只认字典。

`from_attributes=True` 就是开一个开关：
👉 允许 Pydantic 直接伸手去这个盒子上，挨个读里面的变量，组装成返回模型。

举个生活化例子：
    - 不加这个开关：Pydantic 只认一张写满键值的纸条（dict），你给它一个盒子，它看不懂，报错。
    - 加上这个开关：Pydantic 会自己去盒子上找 `.id`、`.name` 这些东西拿出来用。

一句话浓缩：
    开了这个，ORM 对象可以直接喂给 Pydantic 校验转模型，不用你手动转成字典。

额外小提醒：
    名字要对上！盒子上叫 `name`，Pydantic 类里也必须叫 `name`，不然找不到。
"""


class LabResponse(BaseModel):
    id: int
    name: str
    location: str | None = None
    capacity: int
    open_time: str | None = None
    close_time: str | None = None
    description: str | None = None
    img: str | None = None
    status: int

    """
    `from_attributes=True` 只有一种场景才需要：
        你要把【ORM 对象（数据库查出来的对象盒子）】喂给这个 Pydantic 模型。
        请求类（Create / Update）接收的是前端传过来的 JSON → 转字典，全程都是字典，不需要这个开关。
    """
    model_config = ConfigDict(from_attributes=True)


class LabCreateRequest(BaseModel):
    name: str
    location: str | None = None
    capacity: int = 0
    open_time: str | None = None
    close_time: str | None = None
    description: str | None = None
    img: str | None = None
    status: int = 1


class LabUpdateRequest(BaseModel):
    name: str | None = None
    location: str | None = None
    capacity: int | None = None
    open_time: str | None = None
    close_time: str | None = None
    description: str | None = None
    img: str | None = None
    status: int | None = None
