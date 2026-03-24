export function binData(xData, yData, numBuckets) {
  if (!Array.isArray(xData) || !Array.isArray(yData)) {
    throw new Error("xData and yData must be arrays.");
  }
  if (xData.length !== yData.length || xData.length === 0 || numBuckets < 1) {
    return [];
  }

  const minX = xData.reduce((minimum, value) => (value < minimum ? value : minimum), xData[0]);
  const maxX = xData.reduce((maximum, value) => (value > maximum ? value : maximum), xData[0]);

  if (minX === maxX) {
    const sumY = yData.reduce((sum, value) => sum + value, 0);
    const sumY2 = yData.reduce((sum, value) => sum + value * value, 0);
    const count = yData.length;
    const meanY = sumY / count;
    const variance = sumY2 / count - meanY * meanY;
    return [{ x: minX, y: meanY, std: Math.sqrt(Math.max(variance, 0)), count, xMean: minX }];
  }

  const binWidth = (maxX - minX) / numBuckets;
  const bins = Array.from({ length: numBuckets }, () => ({
    sumX: 0,
    sumY: 0,
    sumY2: 0,
    count: 0,
  }));

  for (let index = 0; index < xData.length; index += 1) {
    let binIndex = Math.floor(((xData[index] - minX) / (maxX - minX)) * numBuckets);
    if (binIndex === numBuckets) {
      binIndex = numBuckets - 1;
    }
    const bin = bins[binIndex];
    bin.sumX += xData[index];
    bin.sumY += yData[index];
    bin.sumY2 += yData[index] * yData[index];
    bin.count += 1;
  }

  const result = [];
  for (let index = 0; index < numBuckets; index += 1) {
    const bin = bins[index];
    const binStart = minX + index * binWidth;
    const binCenter = binStart + binWidth / 2;
    if (!bin.count) {
      continue;
    }
    const meanY = bin.sumY / bin.count;
    const meanY2 = bin.sumY2 / bin.count;
    const variance = meanY2 - meanY * meanY;
    result.push({
      x: binCenter,
      y: meanY,
      std: Math.sqrt(Math.max(variance, 0)),
      count: bin.count,
      xMean: bin.sumX / bin.count,
    });
  }
  return result;
}
