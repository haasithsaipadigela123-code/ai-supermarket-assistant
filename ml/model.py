import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures


def predict_revenue_next_7_days(admin_id):
    from app import db, Sale
    rows = (db.session.query(Sale.sale_date, db.func.sum(Sale.total).label("revenue"))
            .filter(Sale.admin_id == admin_id)
            .group_by(Sale.sale_date).order_by(Sale.sale_date).all())
    result = {"dates":[],"historical_dates":[],"historical":[],"predicted":[],"has_data":False}
    if len(rows) < 3:
        today = datetime.today().date()
        for i in range(7):
            result["dates"].append((today + timedelta(days=i+1)).strftime("%b %d"))
            result["predicted"].append(0)
        return result
    result["has_data"] = True
    df = pd.DataFrame([{"sale_date": r.sale_date, "revenue": float(r.revenue)} for r in rows])
    df["sale_date"] = pd.to_datetime(df["sale_date"])
    df = df.sort_values("sale_date").reset_index(drop=True)
    X = np.array(range(len(df))).reshape(-1, 1)
    y = df["revenue"].values
    degree = min(2, len(df)-1)
    poly = PolynomialFeatures(degree=degree)
    Xp = poly.fit_transform(X)
    model = LinearRegression().fit(Xp, y)
    for _, row in df.iterrows():
        result["historical_dates"].append(row["sale_date"].strftime("%b %d"))
        result["historical"].append(round(float(row["revenue"]), 2))
    last_date = df["sale_date"].iloc[-1]
    for i in range(1, 8):
        fut = len(df) + i
        pred = model.predict(poly.transform([[fut]]))[0]
        result["dates"].append((last_date + timedelta(days=i)).strftime("%b %d"))
        result["predicted"].append(round(max(0.0, float(pred)), 2))
    return result


def predict_product_demand(admin_id):
    from app import db, Product, Sale
    rows = (db.session.query(
                Product.id, Product.brand, Product.stock,
                db.func.coalesce(db.func.sum(Sale.quantity), 0).label("total_sold"),
                db.func.count(db.func.distinct(Sale.sale_date)).label("days_active"))
            .outerjoin(Sale, db.and_(Sale.product == Product.brand, Sale.admin_id == admin_id))
            .filter(Product.admin_id == admin_id)
            .group_by(Product.id, Product.brand, Product.stock).all())
    results = []
    for r in rows:
        days = max(1, r.days_active)
        avg_daily = r.total_sold / days
        predicted7 = round(avg_daily * 7, 1)
        stock = r.stock
        if stock < predicted7: status = "danger"
        elif stock < predicted7 * 1.5: status = "warning"
        else: status = "ok"
        days_out = int(stock / avg_daily) if avg_daily > 0 else 999
        results.append({"brand": r.brand, "stock": int(stock), "avg_daily": round(avg_daily, 2),
            "predicted_7": predicted7, "restock_qty": max(0, round(predicted7*2-stock, 0)),
            "status": status, "days_until_stockout": min(days_out, 999)})
    return sorted(results, key=lambda x: x["days_until_stockout"])


def get_restock_recommendations(admin_id):
    return [p for p in predict_product_demand(admin_id) if p["status"] in ("danger","warning")]


def get_product_trends(admin_id):
    from app import db, Sale
    rows = (db.session.query(Sale.product, Sale.sale_date, db.func.sum(Sale.quantity).label("qty"))
            .filter(Sale.admin_id == admin_id)
            .group_by(Sale.product, Sale.sale_date)
            .order_by(Sale.product, Sale.sale_date).all())
    if not rows:
        return []
    df = pd.DataFrame([{"product": r.product, "sale_date": r.sale_date, "qty": r.qty} for r in rows])
    trends = []
    for product, grp in df.groupby("product"):
        grp = grp.reset_index(drop=True)
        if len(grp) < 2:
            direction, arrow = "stable", "→"
        else:
            h1 = grp["qty"].iloc[:len(grp)//2].mean()
            h2 = grp["qty"].iloc[len(grp)//2:].mean()
            if h2 > h1*1.1: direction, arrow = "growing", "↑"
            elif h2 < h1*0.9: direction, arrow = "declining", "↓"
            else: direction, arrow = "stable", "→"
        trends.append({"product": product, "total_sold": int(grp["qty"].sum()),
                        "direction": direction, "arrow": arrow})
    return sorted(trends, key=lambda x: x["total_sold"], reverse=True)
