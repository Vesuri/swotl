/* Native, bounded installer for Air Combat Classics (LucasArts, 1993): the
 * SWOTL 2.2 game files from the user's three ACC floppies, given as a drawer
 * with Disk1.img..Disk3.img (720K/1.44M FAT12 images) or the files
 * CLASSICS.001..003 copied from them; or the user's Their Finest Hour sfx.rsc.
 *
 * The three volumes are one INSTALIT archive: PKWARE DCL streams, one per
 * file, with the catalog in the last bytes of CLASSICS.001. Every volume is
 * checked by SHA-256 first; each file by its catalog size and CRC-32.
 * Destination must be new; on any failure the files created are removed. */
#include "io.h"
#include "sha256.h"
#include "blast.h"
#include <string.h>

#define VOLUMES 3
#define CATALOG 1204461UL       /* CLASSICS.001: archive data, then the catalog */
#define RECORD 55
#define RECORDS 808
#define SWOTL_FILES 539         /* product 1, minus the DOS installer files */
#define SFX_SIZE 108002UL

static const uint32_t volume_size[VOLUMES]={1251008UL,1457152UL,481082UL};
/* SHA-256 of CLASSICS.001..003 and of TFH sfx.rsc (shasum -a 256). */
static const unsigned char volume_sha[VOLUMES][32]={
    {0xd1,0x64,0x43,0xf2,0x07,0xdb,0xce,0x90,0x3b,0xa0,0x01,0xbb,0x7b,0x6d,0x21,0x5b,
     0xf5,0xaa,0xa3,0x1f,0x8e,0x20,0x07,0x54,0x98,0x58,0x54,0x2c,0x60,0x29,0x90,0x40},
    {0x26,0x54,0x26,0xf6,0x0c,0x4c,0x83,0xa9,0xd1,0x15,0x6b,0x8d,0x4c,0xab,0x82,0x00,
     0x29,0x11,0xac,0x2d,0x0e,0xc2,0x60,0x01,0xa2,0x5a,0x51,0xb0,0xa0,0x26,0xd2,0xf6},
    {0xa2,0x44,0x4e,0x6b,0x10,0x52,0x47,0x68,0x55,0xce,0xe5,0x22,0x84,0xcf,0xa7,0xeb,
     0xf0,0xad,0x37,0x96,0x19,0x81,0x73,0xdc,0x0c,0xb3,0xce,0x5d,0xbe,0x81,0xe0,0x91}};
static const unsigned char sfx_sha[32]=
    {0xed,0x09,0xbc,0x2d,0x5c,0x83,0x80,0xd5,0xe7,0xc1,0xdf,0x24,0x76,0xf3,0x8b,0xf0,
     0xa6,0xd1,0x5c,0x49,0xd0,0xa2,0xb5,0xdd,0xe1,0x94,0x59,0x08,0x13,0x1a,0xdb,0x48};
/* SWOTL's catalog directory indexes 1..6; "" is the game drawer itself. */
static const char *const directory[7]={0,"","AC","CP","FE","FX","MIS"};

typedef struct {
    File f; int image; uint32_t size, data, cluster;
    unsigned clusters; uint16_t chain[2880];
} Volume;
static Volume volume[VOLUMES];
static unsigned char catalog[RECORDS*RECORD], buffer[4096], sector[7168];
static char created[SWOTL_FILES+8][20];
static unsigned count;

static uint32_t le32(const unsigned char *p)
{ return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static unsigned le16(const unsigned char *p) { return p[0]|(unsigned)p[1]<<8; }
static int eq(const char *a,const char *b) { return strlen(a)==strlen(b) && !memcmp(a,b,strlen(a)); }
static int lower_eq(const char *a,const char *b)
{
    while(*a && *b) { char x=*a++,y=*b++; if(x>='A' && x<='Z')x+=32; if(y>='A' && y<='Z')y+=32; if(x!=y)return 0; }
    return !*a && !*b;
}
static int path(char *out,const char *dir,const char *name)
{
    unsigned n=strlen(dir),m=strlen(name);
    if(!n || n+m+2>512) return 0;
    memcpy(out,dir,n); if(out[n-1]!=':' && out[n-1]!='/') out[n++]='/';
    memcpy(out+n,name,m+1); return 1;
}
static uint32_t crc_table[256];
static uint32_t crc32(uint32_t c,const unsigned char *p,uint32_t n)
{
    if(!crc_table[1])
        for(unsigned k=0;k<256;k++) {
            uint32_t v=k; for(unsigned i=0;i<8;++i)v=(v>>1)^(0xedb88320UL & (0UL-(v&1)));
            crc_table[k]=v;
        }
    c=~c;
    while(n--) c=crc_table[(c^*p++)&255]^(c>>8);
    return ~c;
}

/* One volume: CLASSICS.00n itself, or its FAT12 chain inside a disk image. */
static int open_image(Volume *v,unsigned n)
{
    static const char name[11]={'C','L','A','S','S','I','C','S','0','0','0'};
    unsigned char *b=sector;
    unsigned bps,spc,reserved,fats,roots,spf,i,c;
    if(!io_read(&v->f,b,512)) return 0;
    bps=le16(b+11); spc=b[13]; reserved=le16(b+14); fats=b[16]; roots=le16(b+17); spf=le16(b+22);
    if(bps!=512 || !spc || spc>8 || !reserved || fats<1 || fats>2 || !roots || roots>224 || !spf || spf>12) return 0;
    v->cluster=spc*512UL;
    v->data=(reserved+fats*spf)*512UL+roots*32UL;
    if(v->data>=v->f.size || !io_seek(&v->f,(reserved+fats*spf)*512UL) || !io_read(&v->f,b,roots*32)) return 0;
    for(i=0;i<roots;i++) {
        unsigned char *e=b+32*i;
        if(!memcmp(e,name,10) && e[10]=='0'+n && !(e[11]&0x18)) break;
    }
    if(i==roots) return 0;
    v->size=le32(b+32*i+28); c=le16(b+32*i+26);
    if(!io_seek(&v->f,reserved*512UL) || !io_read(&v->f,b,spf*512)) return 0;
    for(v->clusters=0;c>=2 && c<0xff8;) {
        uint32_t at=v->data+(c-2)*v->cluster,e=c+c/2;
        if(v->clusters>=2880 || at+v->cluster>v->f.size || e+1>=spf*512U) return 0;
        v->chain[v->clusters++]=(uint16_t)c;
        c=c&1?le16(b+e)>>4:le16(b+e)&0xfff;
    }
    return v->clusters==(v->size+v->cluster-1)/v->cluster;
}
static int open_volume(Volume *v,const char *source,unsigned n)
{
    static char name[]="CLASSICS.000",image[]="Disk0.img",ima[]="Disk0.ima";
    char target[512];
    name[11]=(char)('0'+n); image[4]=ima[4]=(char)('0'+n);
    v->image=0;
    if(path(target,source,name) && io_open(&v->f,target,0)) { v->size=v->f.size; return 1; }
    if((path(target,source,image) && io_open(&v->f,target,0)) || (path(target,source,ima) && io_open(&v->f,target,0)))
        { v->image=1; if(open_image(v,n)) return 1; io_close(&v->f); }
    return 0;
}
static int read_volume(Volume *v,uint32_t off,unsigned char *out,uint32_t n)
{
    while(n) {
        uint32_t k=n,at=off;
        if(v->image) {
            uint32_t in=off%v->cluster;
            if(off/v->cluster>=v->clusters) return 0;
            at=v->data+(v->chain[off/v->cluster]-2)*v->cluster+in;
            if(k>v->cluster-in) k=v->cluster-in;
        }
        if(off+k>v->size || !io_seek(&v->f,at) || !io_read(&v->f,out,k)) return 0;
        off+=k; out+=k; n-=k;
    }
    return 1;
}

/* The archive data as one stream: CLASSICS.001 up to its catalog, then 002, 003. */
typedef struct { uint32_t pos, left; int error; } Input;
static unsigned input(void *how,unsigned char **buf)
{
    Input *in=how; uint32_t n=in->left,pos=in->pos; unsigned v=0;
    uint32_t end=CATALOG;
    if(!n || io_cancelled()) return 0;
    while(v<VOLUMES-1 && pos>=end) { pos-=end; end=volume_size[++v]; }
    if(n>sizeof buffer) n=sizeof buffer;
    if(n>end-pos) n=end-pos;
    if(!read_volume(&volume[v],pos,buffer,n)) { in->error=1; return 0; }
    in->pos+=n; in->left-=n; *buf=buffer; return (unsigned)n;
}
typedef struct { File *f; uint32_t size, crc, limit; } Output;
static int output(void *how,unsigned char *buf,unsigned len)
{
    Output *out=how;
    if(len>out->limit-out->size) return 1;
    out->size+=len; out->crc=crc32(out->crc,buf,len);
    return !io_write(out->f,buf,len);
}

static int install_sfx(const char *source,const char *dest)
{
    File f={0},out={0}; SHA256 sha; unsigned char hash[32]; char target[512]; int made=0,ok=0;
    io_message("Checking Their Finest Hour sfx.rsc...");
    if(io_exists(dest)) { io_message("Destination exists; refusing to replace files."); return 20; }
    if(!io_open(&f,source,0) || f.size!=SFX_SIZE) { io_message("sfx.rsc missing or not 108002 bytes."); goto done; }
    sha_init(&sha);
    while(f.pos<f.size) {
        uint32_t n=f.size-f.pos; if(n>sizeof buffer)n=sizeof buffer;
        if(io_cancelled() || !io_read(&f,buffer,n)) goto done;
        sha_update(&sha,buffer,n);
    }
    sha_final(&sha,hash);
    if(memcmp(hash,sfx_sha,32)) { io_message("Unsupported sfx.rsc. Use the one from the Amiga Their Finest Hour."); goto done; }
    if(!io_mkdir(dest)) goto done;
    made=1;
    if(!path(target,dest,"sfx.rsc") || !io_seek(&f,0) || !io_open(&out,target,1)) goto done;
    while(f.pos<f.size) {
        uint32_t n=f.size-f.pos; if(n>sizeof buffer)n=sizeof buffer;
        if(!io_read(&f,buffer,n) || !io_write(&out,buffer,n)) goto done;
    }
    ok=io_close(&out);
done:
    io_close(&out); io_close(&f);
    if(!ok && made) { if(path(target,dest,"sfx.rsc"))io_remove(target); io_remove(dest); }
    io_message(ok?"Copied sfx.rsc.":"Copy failed or cancelled; existing installations were not changed.");
    return ok?0:20;
}

int install_data(const char *source,const char *dest,const char *temp)
{
    File out={0}; SHA256 sha; unsigned char hash[32]; char target[512];
    unsigned v,r,dirs=0,files=0; int ok=0;
    unsigned n=strlen(source);
    (void)temp; count=0;
    if(n>=7 && lower_eq(source+n-7,"sfx.rsc")) return install_sfx(source,dest);
    if(io_exists(dest)) { io_message("Destination exists; refusing to replace files."); return 20; }
    io_message("Checking the Air Combat Classics disks...");
    for(v=0;v<VOLUMES;v++) {
        uint32_t pos;
        if(!open_volume(&volume[v],source,v+1)) {
            io_message("Disk image or CLASSICS file missing. Need Disk1.img, Disk2.img, Disk3.img or CLASSICS.001-003.");
            goto done;
        }
        if(volume[v].size!=volume_size[v]) { io_message("Unsupported disks. Use the Air Combat Classics floppies."); goto done; }
        sha_init(&sha);
        for(pos=0;pos<volume[v].size;) {
            uint32_t k=volume[v].size-pos; if(k>sizeof buffer)k=sizeof buffer;
            if(io_cancelled() || !read_volume(&volume[v],pos,buffer,k)) goto done;
            sha_update(&sha,buffer,k); pos+=k;
        }
        sha_final(&sha,hash);
        if(memcmp(hash,volume_sha[v],32)) { io_message("Unsupported or damaged disks. Use the Air Combat Classics floppies."); goto done; }
    }
    if(!read_volume(&volume[0],CATALOG+6,catalog,sizeof catalog)) goto done;
    if(!io_mkdir(dest)) goto done;
    memcpy(created[count++],"",1);
    for(dirs=2;dirs<7;dirs++) {
        if(!path(target,dest,directory[dirs]) || !io_mkdir(target)) goto done;
        memcpy(created[count++],directory[dirs],strlen(directory[dirs])+1);
    }
    io_message("Extracting Secret Weapons of the Luftwaffe...");
    for(r=0;r<RECORDS;r++) {
        const unsigned char *e=catalog+r*RECORD;
        char name[14],file[20]; unsigned d,disk,dir; uint32_t start,comp,size;
        Input in; Output o; unsigned left=0;
        if(e[0]!=0x1c || e[5]!=0xf0) goto done;
        if(le16(e+39)!=1) continue;                      /* BattleHawks, Their Finest Hour */
        memcpy(name,e+6,13); name[13]=0;
        if(eq(name,"INSTALL.EXE") || eq(name,"INSTALL2.BAT") || eq(name,"READ.ME")) continue;
        disk=e[32]; dir=le16(e+51); comp=le32(e+20); size=le32(e+35);
        if(disk<1 || disk>VOLUMES || dir<1 || dir>6 || !strlen(name) || files>=SWOTL_FILES) goto done;
        for(d=0;name[d];d++) if(!((name[d]>='A' && name[d]<='Z') || (name[d]>='0' && name[d]<='9') || name[d]=='.' || name[d]=='-' || name[d]=='_')) goto done;
        start=le32(e+1);
        for(d=1;d<disk;d++) start+=d==1?CATALOG:volume_size[d-1];
        if(dir==1) memcpy(file,name,strlen(name)+1);
        else { unsigned k=strlen(directory[dir]); memcpy(file,directory[dir],k); file[k]='/'; memcpy(file+k+1,name,strlen(name)+1); }
        if(!path(target,dest,file) || io_exists(target) || !io_open(&out,target,1)) goto done;
        memcpy(created[count++],file,strlen(file)+1);
        in.pos=start; in.left=comp; in.error=0;
        o.f=&out; o.size=0; o.crc=0; o.limit=size;
        if(blast(input,&in,output,&o,&left,0) || in.error || left || in.left || o.size!=size || o.crc!=le32(e+28) || !io_close(&out)) {
            io_message("Damaged archive data. Use the Air Combat Classics floppies.");
            goto done;
        }
        files++;
    }
    if(files!=SWOTL_FILES) goto done;
    ok=1; io_message("Installed 539 Secret Weapons of the Luftwaffe 2.2 files.");
done:
    io_close(&out);
    for(v=0;v<VOLUMES;v++) io_close(&volume[v].f);
    if(!ok) {
        while(count) {
            --count;
            if(!created[count][0]) io_remove(dest);
            else if(path(target,dest,created[count])) io_remove(target);
        }
        io_message("Installation failed or cancelled; existing installations were not changed.");
    }
    return ok?0:20;
}
