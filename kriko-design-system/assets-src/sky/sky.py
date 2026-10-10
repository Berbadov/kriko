import numpy as np
from PIL import Image
RAMP=[(0x05,0x07,0x0f),(0x0a,0x1a,0x66),(0x17,0x39,0xc2),(0x1f,0x4f,0xff),(0x5a,0x82,0xff),(0x86,0xa3,0xff),(0xbf,0xe4,0xff),(0xf2,0xf5,0xff)]
BAY=np.array([[0,32,8,40,2,34,10,42],[48,16,56,24,50,18,58,26],[12,44,4,36,14,46,6,38],[60,28,52,20,62,30,54,22],[3,35,11,43,1,33,9,41],[51,19,59,27,49,17,57,25],[15,47,7,39,13,45,5,37],[63,31,55,23,61,29,53,21]])/64.0
def noise(w,h,cell,rng):
    gw,gh=w//cell+2,h//cell+2
    g=rng.random((gh,gw))
    ys=np.linspace(0,gh-2,h);xs=np.linspace(0,gw-2,w)
    y0=ys.astype(int);x0=xs.astype(int);fy=(ys-y0)[:,None];fx=(xs-x0)[None,:]
    fy=fy*fy*(3-2*fy);fx=fx*fx*(3-2*fx)
    a=g[y0][:,x0];b=g[y0][:,x0+1];c=g[y0+1][:,x0];d=g[y0+1][:,x0+1]
    return a*(1-fx)*(1-fy)+b*fx*(1-fy)+c*(1-fx)*fy+d*fx*fy
def fbm(w,h,seed,base=40):
    rng=np.random.default_rng(seed);t=0;amp=1;tot=0
    for o in range(5):
        t=t+amp*noise(w,h,max(2,base>>o),rng);tot+=amp;amp*=.5
    return t/tot
def sky(W,H,seed,cloud=1.0,fade0=.62,scale=4,name='sky.png'):
    y=np.linspace(0,1,H)[:,None]*np.ones((1,W));x=np.ones((H,1))*np.linspace(0,1,W)[None,:]
    s=0.30+0.16*y
    f=fbm(W,H,seed)
    L=np.clip((x-.52)/.22,0,1);L=L*L*(3-2*L)
    right=np.clip((x-.55)/.45,0,1)**.8
    cl=np.clip((f-.45)*2.7,0,1)*right*cloud*(1-.30*y)*L
    s=np.minimum(s,0.36+0.5*L)
    t=np.clip(s+cl*.62*L,0,1)
    fd=np.clip((y-fade0)/(1-fade0),0,1);fd=fd*fd*(3-2*fd)
    t=t*(1-fd)
    idx=t*(len(RAMP)-1)
    lo=np.floor(idx).astype(int);fr=idx-lo
    thr=np.tile(BAY,(H//8+1,W//8+1))[:H,:W]
    lvl=lo+(fr>thr).astype(int)
    lvl=np.clip(lvl,0,len(RAMP)-1)
    img=np.array(RAMP,dtype=np.uint8)[lvl]
    im=Image.fromarray(img).resize((W*scale,H*scale),Image.NEAREST)
    im.save(name,optimize=True)
    return im
sky(480,120,7,1.0,.80,4,'sky-wide.png')
sky(480,90,21,.55,.80,4,'sky-dim.png')
sky(480,150,3,1.25,.80,4,'sky-hero.png')
