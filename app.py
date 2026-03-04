import os, re, csv, io, calendar
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, session,
                   send_file, jsonify, flash, url_for)
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from flask_sqlalchemy import SQLAlchemy
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "postgresql://user:pass@localhost:5432/supermart"
).replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = app.config["SECRET_KEY"]

db = SQLAlchemy(app)

# ─── Models ───────────────────────────────────────────────────
class Admin(db.Model):
    __tablename__ = "admins"
    id                  = db.Column(db.Integer, primary_key=True)
    admin_name          = db.Column(db.String(120), nullable=False)
    supermarket_name    = db.Column(db.String(200), nullable=False)
    username            = db.Column(db.String(80), unique=True, nullable=False)
    password            = db.Column(db.String(256), nullable=False)
    shop_address        = db.Column(db.Text, default="")
    shop_phone          = db.Column(db.String(40), default="")
    shop_gst            = db.Column(db.String(40), default="")
    revenue_goal        = db.Column(db.Float, default=0)
    low_stock_threshold = db.Column(db.Integer, default=10)
    expiry_warning_days = db.Column(db.Integer, default=30)
    products  = db.relationship("Product",  backref="admin", lazy=True, cascade="all,delete")
    customers = db.relationship("Customer", backref="admin", lazy=True, cascade="all,delete")
    sales     = db.relationship("Sale",     backref="admin", lazy=True, cascade="all,delete")

class Product(db.Model):
    __tablename__ = "products"
    id       = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=False)
    brand    = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), default="General")
    price    = db.Column(db.Float, nullable=False)
    stock    = db.Column(db.Integer, nullable=False)
    expiry   = db.Column(db.Date, nullable=True)

class Customer(db.Model):
    __tablename__ = "customers"
    id       = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=False)
    name     = db.Column(db.String(200), nullable=False)
    phone    = db.Column(db.String(40), default="")

class Sale(db.Model):
    __tablename__ = "sales"
    id        = db.Column(db.Integer, primary_key=True)
    admin_id  = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=False)
    customer  = db.Column(db.String(200))
    product   = db.Column(db.String(200))
    quantity  = db.Column(db.Integer)
    gst       = db.Column(db.Float)
    total     = db.Column(db.Float)
    sale_date = db.Column(db.Date)
    sale_time = db.Column(db.Time)

with app.app_context():
    db.create_all()

# ─── Auth ─────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    return decorated

def current_admin():
    return db.session.get(Admin, session["admin_id"])

def get_alert_count():
    try:
        adm    = current_admin()
        cutoff = datetime.today().date() + timedelta(days=adm.expiry_warning_days)
        low    = Product.query.filter_by(admin_id=adm.id).filter(Product.stock < adm.low_stock_threshold).count()
        expir  = Product.query.filter_by(admin_id=adm.id).filter(
            Product.expiry != None,
            Product.expiry <= cutoff,
            Product.expiry >= datetime.today().date()).count()
        return low + expir
    except Exception:
        return 0

# ─── Login / Register / Logout ────────────────────────────────
@app.route("/", methods=["GET","POST"])
def login():
    if "admin_id" in session:
        return redirect("/dashboard")
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        user = Admin.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session.update({
                "admin_id": user.id, "user": user.username,
                "supermarket": user.supermarket_name, "admin_name": user.admin_name,
                "revenue_goal": user.revenue_goal or 0,
                "low_stock_threshold": user.low_stock_threshold or 10,
                "expiry_warning_days": user.expiry_warning_days or 30,
            })
            return redirect("/dashboard")
        return render_template("login.html", error="Invalid username or password")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect("/")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        admin_name  = request.form.get("admin_name","").strip()
        supermarket = request.form.get("supermarket","").strip()
        username    = request.form.get("username","").strip().lower()
        password    = request.form.get("password","")
        confirm     = request.form.get("confirm_password","")
        errors = []
        if not all([admin_name, supermarket, username, password]):
            errors.append("All fields are required.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if not re.match(r'^[a-z0-9_]+$', username):
            errors.append("Username: lowercase letters, numbers, underscores only.")
        if errors:
            return render_template("register.html", errors=errors, form=request.form)
        if Admin.query.filter_by(username=username).first():
            return render_template("register.html", errors=["Username already exists."], form=request.form)
        admin = Admin(admin_name=admin_name, supermarket_name=supermarket,
                      username=username, password=generate_password_hash(password))
        db.session.add(admin); db.session.commit()
        flash("Account created! Please log in.", "success")
        return redirect("/")
    return render_template("register.html")

# ─── Dashboard ────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    aid = session["admin_id"]
    total_products  = Product.query.filter_by(admin_id=aid).count()
    total_customers = Customer.query.filter_by(admin_id=aid).count()
    total_revenue   = db.session.query(db.func.coalesce(db.func.sum(Sale.total),0)).filter_by(admin_id=aid).scalar()
    adm             = current_admin()
    low_stock       = Product.query.filter_by(admin_id=aid).filter(Product.stock < adm.low_stock_threshold).count()

    today = datetime.today().date()
    days7 = [(today - timedelta(days=6-i)) for i in range(7)]
    rev_rows = db.session.query(Sale.sale_date, db.func.sum(Sale.total).label("rev")).filter(
        Sale.admin_id == aid, Sale.sale_date >= (today - timedelta(days=6))
    ).group_by(Sale.sale_date).all()
    rev_map      = {str(r.sale_date): r.rev for r in rev_rows}
    chart_labels = [d.strftime("%b %d") for d in days7]
    chart_data   = [round(rev_map.get(str(d), 0), 2) for d in days7]

    recent_sales = Sale.query.filter_by(admin_id=aid).order_by(
        Sale.sale_date.desc(), Sale.sale_time.desc()).limit(10).all()

    return render_template("dashboard.html",
        total_products=total_products, total_customers=total_customers,
        total_revenue=total_revenue, low_stock=low_stock,
        chart_labels=chart_labels, chart_data=chart_data,
        recent_sales=recent_sales, alert_count=get_alert_count())

# ─── Products ─────────────────────────────────────────────────
@app.route("/products", methods=["GET","POST"])
@login_required
def products():
    aid = session["admin_id"]
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            brand    = request.form.get("brand","").strip()
            category = request.form.get("category","General")
            price    = request.form.get("price","0")
            stock    = request.form.get("stock","0")
            expiry_s = request.form.get("expiry","")
            if not brand:
                flash("Product name is required","error")
            else:
                try:
                    expiry = datetime.strptime(expiry_s,"%Y-%m-%d").date() if expiry_s else None
                    db.session.add(Product(admin_id=aid, brand=brand, category=category,
                                           price=float(price), stock=int(stock), expiry=expiry))
                    db.session.commit(); flash("Product added successfully","success")
                except ValueError:
                    flash("Invalid price or stock value","error")
        elif action == "update":
            try:
                pid      = request.form["id"]
                expiry_s = request.form.get("expiry","")
                expiry   = datetime.strptime(expiry_s,"%Y-%m-%d").date() if expiry_s else None
                p = Product.query.filter_by(id=pid, admin_id=aid).first()
                if p:
                    p.brand=request.form["brand"]; p.category=request.form.get("category","General")
                    p.price=float(request.form["price"]); p.stock=int(request.form["stock"]); p.expiry=expiry
                    db.session.commit(); flash("Product updated","success")
            except (ValueError,KeyError):
                flash("Invalid input","error")
        elif action == "csv_import":
            f = request.files.get("csv_file")
            if f:
                try:
                    content = f.read().decode("utf-8")
                    reader  = csv.DictReader(io.StringIO(content))
                    count   = 0
                    for row in reader:
                        expiry_s = row.get("expiry","")
                        expiry   = datetime.strptime(expiry_s,"%Y-%m-%d").date() if expiry_s else None
                        db.session.add(Product(admin_id=aid, brand=row.get("brand",""),
                            category=row.get("category","General"), price=float(row.get("price",0)),
                            stock=int(row.get("stock",0)), expiry=expiry))
                        count += 1
                    db.session.commit(); flash(f"Imported {count} products","success")
                except Exception as e:
                    db.session.rollback(); flash(f"Import failed: {str(e)}","error")

    search   = request.args.get("q","").strip()
    sort     = request.args.get("sort","id")
    sort_col = {"id":Product.id,"brand":Product.brand,"price":Product.price,
                "stock":Product.stock,"expiry":Product.expiry,"category":Product.category}.get(sort,Product.id)
    query = Product.query.filter_by(admin_id=aid)
    if search:
        query = query.filter(db.or_(Product.brand.ilike(f"%{search}%"),Product.category.ilike(f"%{search}%")))
    prods = query.order_by(sort_col).all()
    return render_template("products.html", products=prods, search=search,
        sort=sort, threshold=current_admin().low_stock_threshold, alert_count=get_alert_count())

@app.route("/delete_product", methods=["POST"])
@login_required
def delete_product():
    pid = request.form.get("product_id")
    if pid:
        p = Product.query.filter_by(id=pid, admin_id=session["admin_id"]).first()
        if p:
            db.session.delete(p); db.session.commit(); flash("Product deleted","success")
    return redirect("/products")

# ─── Billing ──────────────────────────────────────────────────
@app.route("/billing", methods=["GET","POST"])
@login_required
def billing():
    aid  = session["admin_id"]; adm = current_admin()
    custs = Customer.query.filter_by(admin_id=aid).order_by(Customer.name).all()
    prods = Product.query.filter_by(admin_id=aid).filter(Product.stock > 0).order_by(Product.brand).all()

    if request.method == "POST":
        customer = (request.form.get("new_customer") or request.form.get("customer","")).strip().title()
        if request.form.get("new_customer"):
            if not Customer.query.filter_by(admin_id=aid, name=customer).first():
                db.session.add(Customer(admin_id=aid, name=customer))
        selected = request.form.getlist("product")
        shop_name=adm.supermarket_name; shop_addr=adm.shop_address or ""
        shop_phone=adm.shop_phone or ""; shop_gst=adm.shop_gst or ""

        pdf = FPDF(); pdf.add_page(); pdf.set_auto_page_break(auto=True,margin=15)
        pdf.set_font("Arial","B",16); pdf.cell(0,8,shop_name.upper(),ln=1,align="C")
        pdf.set_font("Arial","",10)
        if shop_addr:  pdf.cell(0,6,f"Address: {shop_addr}",ln=1,align="C")
        if shop_phone: pdf.cell(0,6,f"Phone: {shop_phone}",ln=1,align="C")
        if shop_gst:   pdf.cell(0,6,f"GST: {shop_gst}",ln=1,align="C")
        pdf.ln(4); pdf.set_font("Arial","B",12); pdf.cell(0,8,"CASH BILL",ln=1,align="C")
        pdf.ln(5); pdf.set_font("Arial","",10)
        today_str = datetime.today().strftime("%d-%m-%Y")
        pdf.cell(100,6,f"Customer: {customer}",ln=0); pdf.cell(0,6,f"Date: {today_str}",ln=1)
        pdf.ln(5); pdf.set_font("Arial","B",10)
        pdf.cell(10,8,"#",1); pdf.cell(65,8,"Product",1); pdf.cell(20,8,"Qty",1)
        pdf.cell(30,8,"Rate",1); pdf.cell(20,8,"GST",1); pdf.cell(30,8,"Total",1,ln=1)
        pdf.set_font("Arial","",10)
        grand_total=0; sno=1
        for pid in selected:
            qty = int(request.form.get(f"qty_{pid}",0))
            if qty <= 0: continue
            p = Product.query.filter_by(id=pid,admin_id=aid).first()
            if not p: continue
            amount=p.price*qty; gst=amount*0.05; total=amount+gst; grand_total+=total
            db.session.add(Sale(admin_id=aid,customer=customer,product=p.brand,quantity=qty,
                gst=gst,total=total,sale_date=datetime.today().date(),sale_time=datetime.now().time()))
            p.stock -= qty
            pdf.cell(10,8,str(sno),1); pdf.cell(65,8,p.brand[:30],1); pdf.cell(20,8,str(qty),1)
            pdf.cell(30,8,f"{p.price:.2f}",1); pdf.cell(20,8,f"{gst:.2f}",1); pdf.cell(30,8,f"{total:.2f}",1,ln=1)
            sno+=1
        pdf.set_font("Arial","B",11); pdf.cell(145,8,"Grand Total",1); pdf.cell(30,8,f"Rs.{grand_total:.2f}",1,ln=1)
        pdf.ln(10); pdf.set_font("Arial","I",10)
        pdf.cell(0,8,f"Thank you for shopping at {shop_name}!",ln=1,align="C")
        db.session.commit()
        safe_name=re.sub(r'[^a-zA-Z0-9_]','_',shop_name)
        safe_cust=re.sub(r'[^a-zA-Z0-9_]','_',customer)
        filename=f"{safe_name}_{safe_cust}_{datetime.today().strftime('%Y%m%d')}.pdf"
        buf = io.BytesIO(pdf.output(dest="S").encode("latin-1")); buf.seek(0)
        return send_file(buf,as_attachment=True,download_name=filename,mimetype="application/pdf")

    return render_template("billing.html",customers=custs,products=prods,alert_count=get_alert_count())

@app.route("/search_products")
@login_required
def search_products():
    q = request.args.get("q","").lower()
    prods = Product.query.filter_by(admin_id=session["admin_id"]).filter(
        Product.stock>0,Product.brand.ilike(f"%{q}%")).limit(10).all()
    return jsonify({"products":[{"id":p.id,"brand":p.brand,"price":p.price,"stock":p.stock} for p in prods]})

# ─── Sales ────────────────────────────────────────────────────
@app.route("/sales")
@login_required
def sales():
    aid=session["admin_id"]
    from_date=request.args.get("from_date",""); to_date=request.args.get("to_date","")
    search_cust=request.args.get("search","").strip()
    query = Sale.query.filter_by(admin_id=aid)
    if from_date and to_date:
        query = query.filter(Sale.sale_date.between(from_date,to_date))
    if search_cust:
        query = query.filter(Sale.customer.ilike(f"%{search_cust}%"))
    rows = query.order_by(Sale.sale_date.desc(),Sale.sale_time.desc()).all()
    from collections import defaultdict
    grouped = defaultdict(lambda:{"customer":"","product":[],"quantity":[],"gst":0,"total":0,"sale_date":"","sale_time":""})
    for r in rows:
        key=(r.customer,str(r.sale_date),str(r.sale_time))
        g=grouped[key]; g["customer"]=r.customer; g["product"].append(r.product)
        g["quantity"].append(str(r.quantity)); g["gst"]+=r.gst; g["total"]+=r.total
        g["sale_date"]=str(r.sale_date); g["sale_time"]=str(r.sale_time)
    data=[{**v,"product":", ".join(v["product"]),"quantity":", ".join(v["quantity"])} for v in grouped.values()]
    data.sort(key=lambda x:(x["sale_date"],x["sale_time"]),reverse=True)
    grand_total=sum(r.total for r in rows)
    return render_template("sales.html",data=data,count=len(data),from_date=from_date,
        to_date=to_date,search_cust=search_cust,grand_total=grand_total,alert_count=get_alert_count())

@app.route("/download_sales")
@login_required
def download_sales():
    aid=session["admin_id"]
    from_date=request.args.get("from_date",""); to_date=request.args.get("to_date","")
    fmt=request.args.get("format","xlsx")
    query=Sale.query.filter_by(admin_id=aid)
    if from_date and to_date:
        query=query.filter(Sale.sale_date.between(from_date,to_date))
    rows=query.order_by(Sale.sale_date.desc()).all()
    df=pd.DataFrame([{"customer":r.customer,"product":r.product,"quantity":r.quantity,
        "gst":r.gst,"total":r.total,"sale_date":r.sale_date,"sale_time":r.sale_time} for r in rows])
    buf=io.BytesIO()
    if fmt=="csv":
        df.to_csv(buf,index=False); buf.seek(0)
        return send_file(buf,as_attachment=True,download_name="sales.csv",mimetype="text/csv")
    df.to_excel(buf,index=False); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name="sales.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── Alerts ───────────────────────────────────────────────────
@app.route("/alerts")
@login_required
def alerts():
    aid=session["admin_id"]; adm=current_admin()
    threshold=adm.low_stock_threshold; exp_days=adm.expiry_warning_days
    cutoff=datetime.today().date()+timedelta(days=exp_days)
    low_prods = Product.query.filter_by(admin_id=aid).filter(Product.stock<threshold).all()
    exp_prods  = Product.query.filter_by(admin_id=aid).filter(
        Product.expiry!=None,Product.expiry<=cutoff,Product.expiry>=datetime.today().date()).all()
    def to_row(p):
        days_left=(p.expiry-datetime.today().date()).days if p.expiry else None
        return (p.brand,p.stock,str(p.expiry) if p.expiry else None,days_left)
    low_stock=[to_row(p) for p in low_prods]; expiring=[to_row(p) for p in exp_prods]
    seen=set(); all_alerts=[]
    for row in low_stock+expiring:
        if row[0] not in seen: all_alerts.append(row); seen.add(row[0])
    return render_template("alerts.html",low_stock=low_stock,expiring=expiring,
        all_alerts=all_alerts,threshold=threshold,exp_days=exp_days,alert_count=get_alert_count())

# ─── Reports ──────────────────────────────────────────────────
@app.route("/reports",methods=["GET","POST"])
@login_required
def reports():
    aid=session["admin_id"]; chart_path=None; message=None
    from_date=request.args.get("from_date",""); to_date=request.args.get("to_date","")
    chart_type=request.args.get("chart_type","bar")
    if request.method=="POST" and "dataset" in request.files:
        f=request.files["dataset"]
        if f.filename:
            content=f.read().decode("utf-8"); df=pd.read_csv(io.StringIO(content))
            if len(df.columns)>=2:
                x,y=df.columns[0],df.columns[1]
                fig,ax=plt.subplots(figsize=(10,5)); ax.bar(df[x],df[y])
                ax.set_xlabel(x); ax.set_ylabel(y); ax.set_title("Custom Dataset")
                plt.xticks(rotation=45,ha="right"); plt.tight_layout()
                os.makedirs("static/charts",exist_ok=True)
                chart_path="static/charts/report.png"; plt.savefig(chart_path); plt.close()
            else:
                message="Dataset needs at least 2 columns"
    else:
        query=Sale.query.filter_by(admin_id=aid)
        if from_date and to_date:
            query=query.filter(Sale.sale_date.between(from_date,to_date))
        rows=query.all()
        if rows:
            df=pd.DataFrame([{"product":r.product,"quantity":r.quantity} for r in rows])
            df=df.groupby("product")["quantity"].sum().reset_index().sort_values("quantity",ascending=False)
            fig,ax=plt.subplots(figsize=(10,5))
            if chart_type=="pie":
                ax.pie(df["quantity"],labels=df["product"],autopct='%1.1f%%')
            elif chart_type=="line":
                ax.plot(df["product"],df["quantity"],marker='o',color='#3b82f6')
                ax.fill_between(range(len(df)),df["quantity"],alpha=0.2)
                ax.set_xticks(range(len(df))); ax.set_xticklabels(df["product"],rotation=45,ha="right")
            else:
                ax.bar(df["product"],df["quantity"],color='#3b82f6')
                ax.set_xlabel("Product"); ax.set_ylabel("Units Sold"); plt.xticks(rotation=45,ha="right")
            title=f"Sales Report ({from_date} to {to_date})" if from_date and to_date else "Sales Report (All Time)"
            ax.set_title(title); plt.tight_layout()
            os.makedirs("static/charts",exist_ok=True)
            chart_path="static/charts/report.png"; plt.savefig(chart_path); plt.close()
            session["report_from"]=from_date; session["report_to"]=to_date
        else:
            message="No sales data available."
    return render_template("reports.html",chart_path=chart_path,message=message,
        from_date=from_date,to_date=to_date,chart_type=chart_type,alert_count=get_alert_count())

@app.route("/download_report_pdf")
@login_required
def download_report_pdf():
    chart_path="static/charts/report.png"
    if not os.path.exists(chart_path):
        flash("Generate a chart first.","error"); return redirect("/reports")
    from_date=session.get("report_from",""); to_date=session.get("report_to","")
    sub=f"Sales Report ({from_date} to {to_date})" if from_date and to_date else f"Sales Report - {datetime.today().strftime('%B %Y')}"
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4)
    styles=getSampleStyleSheet(); els=[]
    els.append(Paragraph(session.get("supermarket","Supermarket"),styles["Title"]))
    els.append(Spacer(1,10)); els.append(Paragraph(sub,styles["Heading2"]))
    els.append(Spacer(1,20)); els.append(Image(chart_path,width=400,height=250))
    doc.build(els); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name="sales_report.pdf",mimetype="application/pdf")

# ─── Predictions ──────────────────────────────────────────────
@app.route("/predictions")
@login_required
def predictions():
    from ml.model import (predict_revenue_next_7_days,predict_product_demand,
                          get_product_trends,get_restock_recommendations)
    aid=session["admin_id"]; adm=current_admin()
    revenue_pred=predict_revenue_next_7_days(aid)
    demand=predict_product_demand(aid)
    trends=get_product_trends(aid)
    restock=get_restock_recommendations(aid)
    goal=adm.revenue_goal or 0; now=datetime.today()
    month_rev=db.session.query(db.func.coalesce(db.func.sum(Sale.total),0)).filter(
        Sale.admin_id==aid,
        db.func.extract('year',Sale.sale_date)==now.year,
        db.func.extract('month',Sale.sale_date)==now.month).scalar()
    days_in_month=calendar.monthrange(now.year,now.month)[1]; day_of_month=now.day
    daily_avg=(month_rev/day_of_month) if day_of_month>0 else 0
    projected=daily_avg*days_in_month
    goal_pct=min(100,round((month_rev/goal*100),1)) if goal>0 else 0
    on_track=projected>=goal if goal>0 else None
    return render_template("predictions.html",revenue_pred=revenue_pred,demand=demand,
        trends=trends,restock=restock,goal=goal,month_rev=month_rev,goal_pct=goal_pct,
        projected=projected,on_track=on_track,alert_count=get_alert_count())

# ─── Settings ─────────────────────────────────────────────────
@app.route("/settings",methods=["GET","POST"])
@login_required
def settings():
    adm=current_admin()
    if request.method=="POST":
        action=request.form.get("action")
        if action=="update_shop":
            adm.supermarket_name=request.form.get("supermarket_name","").strip()
            adm.shop_address=request.form.get("address","").strip()
            adm.shop_phone=request.form.get("phone","").strip()
            adm.shop_gst=request.form.get("gst_no","").strip()
            db.session.commit(); session["supermarket"]=adm.supermarket_name
            flash("Shop info updated","success")
        elif action=="change_password":
            old=request.form.get("old_password",""); new=request.form.get("new_password",""); cfm=request.form.get("confirm_password","")
            if not check_password_hash(adm.password,old): flash("Current password is incorrect","error")
            elif new!=cfm: flash("New passwords do not match","error")
            elif len(new)<6: flash("Password must be at least 6 characters","error")
            else:
                adm.password=generate_password_hash(new); db.session.commit()
                flash("Password changed successfully","success")
        elif action=="update_prefs":
            adm.revenue_goal=float(request.form.get("revenue_goal",0) or 0)
            adm.low_stock_threshold=int(request.form.get("low_stock_threshold",10) or 10)
            adm.expiry_warning_days=int(request.form.get("expiry_warning_days",30) or 30)
            db.session.commit()
            session.update({"revenue_goal":adm.revenue_goal,
                "low_stock_threshold":adm.low_stock_threshold,
                "expiry_warning_days":adm.expiry_warning_days})
            flash("Preferences updated","success")
        return redirect("/settings")
    s_data={"admin_name":adm.admin_name,"supermarket_name":adm.supermarket_name,
        "address":adm.shop_address or "","phone":adm.shop_phone or "","gst_no":adm.shop_gst or "",
        "revenue_goal":adm.revenue_goal or 0,"low_stock_threshold":adm.low_stock_threshold or 10,
        "expiry_warning_days":adm.expiry_warning_days or 30}
    return render_template("settings.html",s=s_data,alert_count=get_alert_count())

if __name__ == "__main__":
    app.run()
