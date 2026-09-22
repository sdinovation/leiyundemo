'use strict';
// 生成 ecommerce_10k.csv — 10,000 行电商订单数据
// Schema: 订单ID,日期,渠道,品类,商品名,销售额,数量,折扣率,客户ID,状态
// 用途：性能 / 高基数维度 / 大数据量聚合测试

const fs = require('fs');
const path = require('path');

const N = 10000;
const OUT = path.join(__dirname, 'ecommerce_10k.csv');

// 确定性伪随机（避免每次跑 baseline 数据漂移）
let seed = 12345;
function rand() {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  return seed / 0x7fffffff;
}
function pick(arr) { return arr[Math.floor(rand() * arr.length)]; }
function between(min, max) { return Math.floor(rand() * (max - min + 1)) + min; }
function betweenFloat(min, max, dec = 2) {
  const v = rand() * (max - min) + min;
  return Number(v.toFixed(dec));
}

const channels = ['天猫', '京东', '拼多多', '抖音小店'];
const categories = {
  电子产品: { priceMin: 500, priceMax: 3000, names: ['智能手机', '蓝牙耳机', '平板电脑', '智能手表', '笔记本电脑'] },
  服装:     { priceMin: 100, priceMax: 800,  names: ['T恤', '牛仔裤', '连衣裙', '运动鞋', '羽绒服'] },
  食品:     { priceMin: 20,  priceMax: 300,  names: ['坚果礼盒', '巧克力', '饼干', '茶叶', '咖啡豆'] },
  家居:     { priceMin: 50,  priceMax: 2000, names: ['枕头', '床单', '台灯', '收纳箱', '电饭煲'] },
  美妆:     { priceMin: 50,  priceMax: 1000, names: ['口红', '面霜', '精华液', '防晒霜', '面膜'] }
};
const categoryKeys = Object.keys(categories);
const statuses = ['已完成', '已发货', '已下单', '已退货'];
const statusWeights = [0.6, 0.2, 0.15, 0.05]; // 已完成 60%, 已发货 20%, ...

const startDate = new Date('2025-01-01').getTime();
const daySpan = 30; // 30 天

const rows = [];
rows.push('订单ID,日期,渠道,品类,商品名,销售额,数量,折扣率,客户ID,状态');

for (let i = 1; i <= N; i++) {
  const dayOffset = Math.floor(rand() * daySpan);
  const d = new Date(startDate + dayOffset * 86400000);
  const dateStr = d.toISOString().slice(0, 10);
  const cat = pick(categoryKeys);
  const catDef = categories[cat];
  const productName = pick(catDef.names);
  const qty = between(1, 5);
  const unitPrice = betweenFloat(catDef.priceMin, catDef.priceMax);
  const discount = rand() < 0.3 ? betweenFloat(0.05, 0.2) : 0;
  const totalPrice = Number((unitPrice * qty * (1 - discount)).toFixed(2));

  let acc = 0, r = rand(), st;
  for (let s = 0; s < statuses.length; s++) {
    acc += statusWeights[s];
    if (r < acc) { st = statuses[s]; break; }
  }

  rows.push([
    'ORD-' + String(i).padStart(5, '0'),
    dateStr,
    pick(channels),
    cat,
    productName,
    totalPrice,
    qty,
    discount,
    'C' + String(between(1, 500)).padStart(4, '0'),
    st,
  ].join(','));
}

fs.writeFileSync(OUT, rows.join('\n'), 'utf-8');
console.log(`已生成 ${N} 行: ${OUT}`);
console.log(`文件大小: ${(fs.statSync(OUT).size / 1024).toFixed(1)} KB`);