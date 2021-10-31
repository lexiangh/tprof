// Copyright (c) 2019 The Jaeger Authors.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
package spanstore

import (
	"bytes"
	"context"
	"encoding/binary"
	"math/rand"
	"sort"
	"testing"
	"time"

	"github.com/dgraph-io/badger"
	"github.com/stretchr/testify/assert"

	"github.com/jaegertracing/jaeger/model"
	"github.com/jaegertracing/jaeger/storage/spanstore"
)

func TestEncodingTypes(t *testing.T) {
	// JSON encoding
	runWithBadger(t, func(store *badger.DB, t *testing.T) {
		testSpan := createDummySpan()

		cache := NewCacheStore(store, time.Duration(1*time.Hour), true)
		sw := NewSpanWriter(store, cache, time.Duration(1*time.Hour), nil)
		rw := NewTraceReader(store, cache)

		sw.encodingType = jsonEncoding
		err := sw.WriteSpan(&testSpan)
		assert.NoError(t, err)

		tr, err := rw.GetTrace(context.Background(), model.TraceID{Low: 0, High: 1})
		assert.NoError(t, err)
		assert.Equal(t, 1, len(tr.Spans))
	})

	// Unknown encoding write
	runWithBadger(t, func(store *badger.DB, t *testing.T) {
		testSpan := createDummySpan()

		cache := NewCacheStore(store, time.Duration(1*time.Hour), true)
		sw := NewSpanWriter(store, cache, time.Duration(1*time.Hour), nil)
		// rw := NewTraceReader(store, cache)

		sw.encodingType = 0x04
		err := sw.WriteSpan(&testSpan)
		assert.EqualError(t, err, "unknown encoding type: 0x04")
	})

	// Unknown encoding reader
	runWithBadger(t, func(store *badger.DB, t *testing.T) {
		testSpan := createDummySpan()

		cache := NewCacheStore(store, time.Duration(1*time.Hour), true)
		sw := NewSpanWriter(store, cache, time.Duration(1*time.Hour), nil)
		rw := NewTraceReader(store, cache)

		err := sw.WriteSpan(&testSpan)
		assert.NoError(t, err)

		startTime := model.TimeAsEpochMicroseconds(testSpan.StartTime)

		key, _, _ := createTraceKV(&testSpan, protoEncoding, startTime)
		e := &badger.Entry{
			Key:       key,
			ExpiresAt: uint64(time.Now().Add(1 * time.Hour).Unix()),
		}
		e.UserMeta = byte(0x04)

		store.Update(func(txn *badger.Txn) error {
			txn.SetEntry(e)
			return nil
		})

		_, err = rw.GetTrace(context.Background(), model.TraceID{Low: 0, High: 1})
		assert.EqualError(t, err, "unknown encoding type: 0x04")
	})
}

func TestDecodeErrorReturns(t *testing.T) {
	garbage := []byte{0x08}

	_, err := decodeValue(garbage, protoEncoding)
	assert.Error(t, err)

	_, err = decodeValue(garbage, jsonEncoding)
	assert.Error(t, err)
}

func TestSortMergeIdsDuplicateDetection(t *testing.T) {
	// Different IndexSeeks return the same results
	ids := make([][][]byte, 2)
	ids[0] = make([][]byte, 1)
	ids[1] = make([][]byte, 1)
	buf := new(bytes.Buffer)
	binary.Write(buf, binary.BigEndian, uint64(0))
	binary.Write(buf, binary.BigEndian, uint64(156697987635))
	b := buf.Bytes()
	ids[0][0] = b
	ids[1][0] = b

	query := &spanstore.TraceQueryParameters{
		NumTraces: 64,
	}

	traces := sortMergeIds(query, ids)
	assert.Equal(t, 1, len(traces))
}

func TestDuplicateTraceIDDetection(t *testing.T) {
	runWithBadger(t, func(store *badger.DB, t *testing.T) {
		testSpan := createDummySpan()
		cache := NewCacheStore(store, time.Duration(1*time.Hour), true)
		sw := NewSpanWriter(store, cache, time.Duration(1*time.Hour), nil)
		rw := NewTraceReader(store, cache)

		for i := 0; i < 8; i++ {
			testSpan.SpanID = model.SpanID(i)
			testSpan.StartTime = testSpan.StartTime.Add(time.Millisecond)
			err := sw.WriteSpan(&testSpan)
			assert.NoError(t, err)
		}

		traces, err := rw.FindTraceIDs(context.Background(), &spanstore.TraceQueryParameters{
			ServiceName:  "service",
			StartTimeMax: time.Now().Add(time.Hour),
			StartTimeMin: testSpan.StartTime.Add(-1 * time.Hour),
		})

		assert.NoError(t, err)
		assert.Equal(t, 1, len(traces))
	})
}

func createDummySpan() model.Span {
	tid := time.Now()

	dummyKv := []model.KeyValue{
		{
			Key:   "key",
			VType: model.StringType,
			VStr:  "value",
		},
	}

	testSpan := model.Span{
		TraceID: model.TraceID{
			Low:  uint64(0),
			High: 1,
		},
		SpanID:        model.SpanID(0),
		OperationName: "operation",
		Process: &model.Process{
			ServiceName: "service",
			Tags:        dummyKv,
		},
		StartTime: tid.Add(time.Duration(1 * time.Millisecond)),
		Duration:  time.Duration(1 * time.Millisecond),
		Tags:      dummyKv,
		Logs: []model.Log{
			{
				Timestamp: tid,
				Fields:    dummyKv,
			},
		},
	}

	return testSpan
}

func TestMergeJoin(t *testing.T) {
	assert := assert.New(t)

	// Test equals

	left := make([][]byte, 16)
	right := make([][]byte, 16)

	for i := 0; i < 16; i++ {
		left[i] = make([]byte, 4)
		binary.BigEndian.PutUint32(left[i], uint32(i))

		right[i] = make([]byte, 4)
		binary.BigEndian.PutUint32(right[i], uint32(i))
	}

	merged := mergeJoinIds(left, right)
	assert.Equal(16, len(merged))

	// Check order
	assert.Equal(uint32(15), binary.BigEndian.Uint32(merged[15]))

	// Test simple non-equality different size

	merged = mergeJoinIds(left[1:2], right[13:])
	assert.Empty(merged)

	// Different size, some equalities

	merged = mergeJoinIds(left[0:3], right[1:7])
	assert.Equal(2, len(merged))
	assert.Equal(uint32(2), binary.BigEndian.Uint32(merged[1]))
}

func TestIndexScanReturnOrder(t *testing.T) {
	runWithBadger(t, func(store *badger.DB, t *testing.T) {
		testSpan := createDummySpan()
		cache := NewCacheStore(store, time.Duration(1*time.Hour), true)
		sw := NewSpanWriter(store, cache, time.Duration(1*time.Hour), nil)
		rw := NewTraceReader(store, cache)

		for i := 0; i < 1000; i++ {
			testSpan.TraceID = model.TraceID{
				High: rand.Uint64(),
				Low:  uint64(rand.Int63()),
			}
			testSpan.SpanID = model.SpanID(rand.Uint64())
			testSpan.StartTime = testSpan.StartTime.Add(time.Duration(i) * time.Millisecond)
			err := sw.WriteSpan(&testSpan)
			assert.NoError(t, err)
		}

		tqp := &spanstore.TraceQueryParameters{
			ServiceName:  "service",
			StartTimeMax: testSpan.StartTime.Add(time.Hour),
			StartTimeMin: testSpan.StartTime.Add(-1 * time.Hour),
		}

		indexSeeks := make([][]byte, 0, 1)
		indexSeeks = serviceQueries(tqp, indexSeeks)

		ids := make([][][]byte, 0, len(indexSeeks)+1)

		indexResults, _ := rw.indexSeeksToTraceIDs(tqp, indexSeeks, ids)
		assert.True(t, sort.SliceIsSorted(indexResults[0], func(i, j int) bool {
			return bytes.Compare(indexResults[0][i], indexResults[0][j]) < 0
		}))
	})
}
