"""REGLAS DE ENTRADA: para cada posicion BTC se reconstruye el CONTEXTO DE PRECIO
previo (solo informacion disponible en el momento de abrir) y se mide si predice
el resultado. Validado en 2 periodos de calendario: solo sirve lo consistente."""
import csv, bisect, statistics as st, collections, math, datetime as dt

K=[]
for r in csv.DictReader(open('ohlc/btcusdt_1h.csv')):
    K.append((int(r['open_ms']), float(r['high']), float(r['low']), float(r['close'])))
K.sort(); ks=[x[0] for x in K]; cl=[x[3] for x in K]; hi=[x[1] for x in K]; lo=[x[2] for x in K]

def ix(ms):
    i=bisect.bisect_right(ks,ms)-1
    return i if 0<=i<len(K) else None

def ctx(i):
    """Contexto previo a la entrada. Solo mira hacia atras."""
    if i is None or i<200: return None
    c=cl[i]
    r24=(c/cl[i-24]-1); r4=(c/cl[i-4]-1); r72=(c/cl[i-72]-1)
    w=cl[i-200:i+1]
    ma200=sum(w)/len(w)
    hh=max(hi[i-168:i+1]); ll=min(lo[i-168:i+1])
    posr=(c-ll)/(hh-ll) if hh>ll else .5          # donde esta dentro del rango de 7d
    rets=[cl[j]/cl[j-1]-1 for j in range(i-72,i+1)]
    vol=st.pstdev(rets)*math.sqrt(24)             # vol diaria realizada
    return dict(r4=r4, r24=r24, r72=r72, ma=(c/ma200-1), posr=posr, vol=vol)

P=[]
for r in csv.DictReader(open('binance_positions.csv')):
    if r['symbol']!='BTCUSDT': continue
    try:
        o=int(r['opened_ms']); notio=float(r['notional']); pnl=float(r['closing_pnl'])
    except: continue
    if notio<=0: continue
    net=pnl/notio
    if abs(net)>3: continue
    c=ctx(ix(o))
    if not c: continue
    c.update(net=net, o=o, side=1 if r['side']=='Long' else -1, dur=float(r['dur_h'] or 0))
    P.append(c)
P.sort(key=lambda z:z['o']); CUT=P[len(P)//2]['o']
A=[z for z in P if z['o']<CUT]; B=[z for z in P if z['o']>=CUT]
print(f"posiciones con contexto: {len(P)} | corte {dt.datetime.fromtimestamp(CUT/1000, dt.UTC):%Y-%m-%d}\n")

def mwu_z(a,b):
    na,nb=len(a),len(b)
    if na<20 or nb<20: return 0.0
    v=sorted([(x,0) for x in a]+[(x,1) for x in b]); r=0.0; i=0
    while i<len(v):
        j=i
        while j+1<len(v) and v[j+1][0]==v[i][0]: j+=1
        rk=(i+j)/2.0+1
        for q in range(i,j+1):
            if v[q][1]==0: r+=rk
        i=j+1
    u=r-na*(na+1)/2.0; mu=na*nb/2.0; sd=math.sqrt(na*nb*(na+nb+1)/12.0)
    return (u-mu)/sd

# features de entrada, en terciles calculados sobre el periodo 1 (sin mirar P2)
FE=[('mom 4h','r4'),('mom 24h','r24'),('mom 72h','r72'),
    ('dist MA200h','ma'),('pos en rango 7d','posr'),('volatilidad 72h','vol')]
print(f"{'feature':<18}{'tercil':<8}{'P1 n':>6}{'P1 med%':>9}{'P2 n':>6}{'P2 med%':>9}{'signo':>9}{'z(P2)':>7}")
print('-'*72)
for name,kk in FE:
    vals=sorted(z[kk] for z in A); q1=vals[len(vals)//3]; q2=vals[2*len(vals)//3]
    def t(z): return 'bajo' if z[kk]<q1 else 'medio' if z[kk]<q2 else 'alto'
    for lab in ('bajo','medio','alto'):
        a=[z['net'] for z in A if t(z)==lab]; b=[z['net'] for z in B if t(z)==lab]
        if len(a)<30 or len(b)<30: continue
        m1,m2=st.median(a),st.median(b)
        rest=[z['net'] for z in B if t(z)!=lab]
        cons='consist' if (m1>0)==(m2>0) else 'FLIP'
        print(f"{name:<18}{lab:<8}{len(a):>6}{m1*100:>9.3f}{len(b):>6}{m2*100:>9.3f}{cons:>9}{mwu_z(b,rest):>7.2f}")
    print()

# interaccion clave: momentum x lado (entrar a favor o en contra del movimiento reciente)
print("=== momentum 24h x LADO (¿entrar a favor o contra?) ===")
print(f"{'celda':<22}{'P1 n':>6}{'P1 med%':>9}{'P2 n':>6}{'P2 med%':>9}{'signo':>9}{'z(P2)':>7}")
def cell(z):
    d='sube' if z['r24']>0 else 'baja'
    s='Long' if z['side']==1 else 'Short'
    return f"{d}+{s}"
for lab in ('sube+Long','sube+Short','baja+Long','baja+Short'):
    a=[z['net'] for z in A if cell(z)==lab]; b=[z['net'] for z in B if cell(z)==lab]
    if len(a)<30 or len(b)<30: continue
    m1,m2=st.median(a),st.median(b)
    rest=[z['net'] for z in B if cell(z)!=lab]
    cons='consist' if (m1>0)==(m2>0) else 'FLIP'
    print(f"{lab:<22}{len(a):>6}{m1*100:>9.3f}{len(b):>6}{m2*100:>9.3f}{cons:>9}{mwu_z(b,rest):>7.2f}")
