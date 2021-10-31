// Copyright (c) 2018 The Jaeger Authors.
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
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/dgraph-io/badger"
	"github.com/golang/protobuf/proto"

	"github.com/jaegertracing/jaeger/model"
	"github.com/jaegertracing/jaeger/storage/spanstore"
)

// Most of these errors are common with the ES and Cassandra backends. Each backend has slightly different validation rules.

var (
	// ErrServiceNameNotSet occurs when attempting to query with an empty service name
	ErrServiceNameNotSet = errors.New("service name must be set")

	// ErrStartTimeMinGreaterThanMax occurs when start time min is above start time max
	ErrStartTimeMinGreaterThanMax = errors.New("min start time is above max")

	// ErrDurationMinGreaterThanMax occurs when duration min is above duration max
	ErrDurationMinGreaterThanMax = errors.New("min duration is above max")

	// ErrMalformedRequestObject occurs when a request object is nil
	ErrMalformedRequestObject = errors.New("malformed request object")

	// ErrStartAndEndTimeNotSet occurs when start time and end time are not set
	ErrStartAndEndTimeNotSet = errors.New("start and end time must be set")

	// ErrUnableToFindTraceIDAggregation occurs when an aggregation query for TraceIDs fail.
	ErrUnableToFindTraceIDAggregation = errors.New("could not find aggregation of traceIDs")

	// ErrNotSupported during development, don't support every option - yet
	ErrNotSupported = errors.New("this query parameter is not supported yet")
)

const (
	defaultNumTraces = 100
	sizeOfTraceID    = 16
	encodingTypeBits = 0x0F
)

// TraceReader reads traces from the local badger store
type TraceReader struct {
	store *badger.DB
	cache *CacheStore
}

// NewTraceReader returns a TraceReader with cache
func NewTraceReader(db *badger.DB, c *CacheStore) *TraceReader {
	return &TraceReader{
		store: db,
		cache: c,
	}
}

func decodeValue(val []byte, encodeType byte) (*model.Span, error) {
	sp := model.Span{}
	switch encodeType {
	case jsonEncoding:
		if err := json.Unmarshal(val, &sp); err != nil {
			return nil, err
		}
	case protoEncoding:
		if err := proto.Unmarshal(val, &sp); err != nil {
			return nil, err
		}
	default:
		return nil, fmt.Errorf("unknown encoding type: %#02x", encodeType)
	}
	return &sp, nil
}

// getTraces enriches TraceIDs to Traces
func (r *TraceReader) getTraces(traceIDs []model.TraceID) ([]*model.Trace, error) {
	// Get by PK
	traces := make([]*model.Trace, 0, len(traceIDs))
	prefixes := make([][]byte, 0, len(traceIDs))

	for _, traceID := range traceIDs {
		prefixes = append(prefixes, createPrimaryKeySeekPrefix(traceID))
	}

	err := r.store.View(func(txn *badger.Txn) error {
		opts := badger.DefaultIteratorOptions
		it := txn.NewIterator(opts)
		defer it.Close()

		val := []byte{}
		for _, prefix := range prefixes {
			spans := make([]*model.Span, 0, 32) // reduce reallocation requirements by defining some initial length

			for it.Seek(prefix); it.ValidForPrefix(prefix); it.Next() {
				// Add value to the span store (decode from JSON / defined encoding first)
				// These are in the correct order because of the sorted nature
				item := it.Item()
				val, err := item.ValueCopy(val)
				if err != nil {
					return err
				}

				sp, err := decodeValue(val, item.UserMeta()&encodingTypeBits)
				if err != nil {
					return err
				}
				spans = append(spans, sp)
			}
			if len(spans) > 0 {
				trace := &model.Trace{
					Spans: spans,
				}
				traces = append(traces, trace)
			}
		}
		return nil
	})

	return traces, err
}

// GetTrace takes a traceID and returns a Trace associated with that traceID
func (r *TraceReader) GetTrace(ctx context.Context, traceID model.TraceID) (*model.Trace, error) {
	traces, err := r.getTraces([]model.TraceID{traceID})
	if err != nil {
		return nil, err
	}
	if len(traces) == 1 {
		return traces[0], nil
	}

	return nil, nil
}

// scanTimeRange returns all the Traces found between startTs and endTs
func (r *TraceReader) scanTimeRange(startTime time.Time, endTime time.Time) ([]*model.Trace, error) {
	// We need to do a full table scan
	traces := make([]*model.Trace, 0)
	startTs := model.TimeAsEpochMicroseconds(startTime)
	endTs := model.TimeAsEpochMicroseconds(endTime)

	err := r.store.View(func(txn *badger.Txn) error {
		opts := badger.DefaultIteratorOptions
		opts.PrefetchValues = true
		it := txn.NewIterator(opts)
		defer it.Close()

		val := []byte{}
		startIndex := []byte{spanKeyPrefix}
		spans := make([]*model.Span, 0)
		prevTraceID := []byte{}
		for it.Seek(startIndex); it.ValidForPrefix(startIndex); it.Next() {
			item := it.Item()

			key := []byte{}
			key = item.KeyCopy(key)

			timestamp := binary.BigEndian.Uint64(key[sizeOfTraceID+1 : sizeOfTraceID+1+8])
			traceID := key[1 : sizeOfTraceID+1]

			if timestamp >= startTs && timestamp <= endTs {
				val, err := item.ValueCopy(val)
				if err != nil {
					return err
				}

				sp, err := decodeValue(val, item.UserMeta()&encodingTypeBits)
				if err != nil {
					return err
				}

				if bytes.Equal(prevTraceID, traceID) {
					// Still processing the same one
					spans = append(spans, sp)
				} else {
					// Process last complete span
					trace := &model.Trace{
						Spans: spans,
					}
					traces = append(traces, trace)

					spans = make([]*model.Span, 0, cap(spans)) // Use previous cap
					spans = append(spans, sp)
				}
				prevTraceID = traceID
			}
		}
		if len(spans) > 0 {
			trace := &model.Trace{
				Spans: spans,
			}
			traces = append(traces, trace)
		}

		return nil
	})

	return traces, err
}

func createPrimaryKeySeekPrefix(traceID model.TraceID) []byte {
	key := make([]byte, 1+sizeOfTraceID)
	key[0] = spanKeyPrefix
	pos := 1
	binary.BigEndian.PutUint64(key[pos:], traceID.High)
	pos += 8
	binary.BigEndian.PutUint64(key[pos:], traceID.Low)

	return key
}

// GetServices fetches the sorted service list that have not expired
func (r *TraceReader) GetServices(ctx context.Context) ([]string, error) {
	return r.cache.GetServices()
}

// GetOperations fetches operations in the service and empty slice if service does not exists
func (r *TraceReader) GetOperations(ctx context.Context, service string) ([]string, error) {
	return r.cache.GetOperations(service)
}

// setQueryDefaults alters the query with defaults if certain parameters are not set
func setQueryDefaults(query *spanstore.TraceQueryParameters) {
	if query.NumTraces == 0 {
		query.NumTraces = defaultNumTraces
	}
}

// serviceQueries parses the query to index seeks which are unique index seeks
func serviceQueries(query *spanstore.TraceQueryParameters, indexSeeks [][]byte) [][]byte {
	if query.ServiceName != "" {
		indexSearchKey := make([]byte, 0, 64) // 64 is a magic guess
		if query.OperationName != "" {
			indexSearchKey = append(indexSearchKey, operationNameIndexKey)
			indexSearchKey = append(indexSearchKey, []byte(query.ServiceName+query.OperationName)...)
		} else {
			indexSearchKey = append(indexSearchKey, serviceNameIndexKey)
			indexSearchKey = append(indexSearchKey, []byte(query.ServiceName)...)
		}

		indexSeeks = append(indexSeeks, indexSearchKey)
		if len(query.Tags) > 0 {
			for k, v := range query.Tags {
				tagSearch := []byte(query.ServiceName + k + v)
				tagSearchKey := make([]byte, 0, len(tagSearch)+1)
				tagSearchKey = append(tagSearchKey, tagIndexKey)
				tagSearchKey = append(tagSearchKey, tagSearch...)
				indexSeeks = append(indexSeeks, tagSearchKey)
			}
		}
	}
	return indexSeeks
}

// indexSeeksToTraceIDs does the index scanning against badger based on the parsed index queries
func (r *TraceReader) indexSeeksToTraceIDs(query *spanstore.TraceQueryParameters, indexSeeks [][]byte, ids [][][]byte) ([][][]byte, error) {
	for i, s := range indexSeeks {
		indexResults, err := r.scanIndexKeys(s, query.StartTimeMin, query.StartTimeMax)
		if err != nil {
			return nil, err
		}

		// Same traceID can be returned multiple times, but always in sorted order so checking the previous key is enough
		prevTraceID := []byte{}
		ids = append(ids, make([][]byte, 0, len(indexResults)))
		for _, k := range indexResults {
			traceID := k[len(k)-sizeOfTraceID:]
			if !bytes.Equal(prevTraceID, traceID) {
				ids[i] = append(ids[i], traceID)
				prevTraceID = traceID
			}
		}
		sort.Slice(ids[i], func(k, h int) bool {
			return bytes.Compare(ids[i][k], ids[i][h]) < 0
		})
	}
	return ids, nil
}

// durationQueries checks non unique index of durations
func (r *TraceReader) durationQueries(query *spanstore.TraceQueryParameters, ids [][][]byte) [][][]byte {
	durMax := uint64(model.DurationAsMicroseconds(query.DurationMax))
	durMin := uint64(model.DurationAsMicroseconds(query.DurationMin))

	startKey := make([]byte, 0, 9)
	endKey := make([]byte, 0, 9)

	startKey = append(startKey, durationIndexKey) // [0] =
	endKey = append(endKey, durationIndexKey)

	endVal := make([]byte, 8)
	if query.DurationMax == 0 {
		// Set MAX to infinite, if Min is missing, 0 is a fine search result for us
		durMax = math.MaxUint64
	}
	binary.BigEndian.PutUint64(endVal, durMax)

	startVal := make([]byte, 8)
	binary.BigEndian.PutUint64(startVal, durMin)

	startKey = append(startKey, startVal...)
	endKey = append(endKey, endVal...)

	// This is not unique index result - same TraceID can be matched from multiple spans
	indexResults, _ := r.scanRangeIndex(startKey, endKey, query.StartTimeMin, query.StartTimeMax)
	hashFilter := make(map[model.TraceID]struct{}, len(indexResults))
	filteredResults := make([]*model.TraceID, 0, len(indexResults)) // Max possible length
	appendableResults := make([][]byte, 0, len(indexResults))       // Max possible length
	var value struct{}
	for _, k := range indexResults {
		key := k[len(k)-sizeOfTraceID:]
		id := &model.TraceID{
			High: binary.BigEndian.Uint64(key[:8]),
			Low:  binary.BigEndian.Uint64(key[8:]),
		}
		if _, exists := hashFilter[*id]; !exists {
			filteredResults = append(filteredResults, id)
			hashFilter[*id] = value
		}
	}

	model.SortTraceIDs(filteredResults)

	// This is an ugly hack at this point - but has no impact on performance really
	for _, tr := range filteredResults {
		appendableResults = append(appendableResults, traceIDToComparableBytes(tr))
	}

	ids = append(ids, appendableResults)
	return ids
}

func mergeJoinIds(left, right [][]byte) [][]byte {
	// len(left) or len(right) is the maximum, whichever is the smallest
	allocateSize := len(left)
	if len(right) < allocateSize {
		allocateSize = len(right)
	}

	merged := make([][]byte, 0, allocateSize)

	lMax := len(left) - 1
	rMax := len(right) - 1
	for r, l := 0, 0; r <= rMax && l <= lMax; {
		switch bytes.Compare(left[l], right[r]) {
		case 0:
			// Left matches right - merge
			merged = append(merged, left[l])
			// Advance both
			l++
			r++
		case 1:
			// left > right, increase right one
			r++
		case -1:
			// left < right, increase left one
			l++
		}
	}
	return merged
}

// sortMergeIds does a sort-merge join operation to the list of TraceIDs to remove duplicates
func sortMergeIds(query *spanstore.TraceQueryParameters, ids [][][]byte) []model.TraceID {
	// Key only scan is a lot faster in the badger - use sort-merge join algorithm instead of hash join since we have the keys in sorted order already
	var merged [][]byte

	if len(ids) > 1 {
		merged = mergeJoinIds(ids[0], ids[1])
		for i := 2; i < len(ids); i++ {
			merged = mergeJoinIds(merged, ids[i])
		}
	} else {
		merged = ids[0]
	}

	// Get top query.NumTraces results (order in DESC)
	if query.NumTraces < len(merged) {
		merged = merged[len(merged)-query.NumTraces:]
	}

	// Results are in ASC (badger's default order), but Jaeger uses DESC, thus we need to reverse the array
	for left, right := 0, len(merged)-1; left < right; left, right = left+1, right-1 {
		merged[left], merged[right] = merged[right], merged[left]
	}

	// Create the structs from [][]byte to TraceID
	keys := make([]model.TraceID, 0, len(merged))

	for _, key := range merged {
		keys = append(keys, model.TraceID{
			High: binary.BigEndian.Uint64(key[:8]),
			Low:  binary.BigEndian.Uint64(key[8:]),
		})
	}

	return keys
}

// FindTraces retrieves traces that match the traceQuery
func (r *TraceReader) FindTraces(ctx context.Context, query *spanstore.TraceQueryParameters) ([]*model.Trace, error) {
	keys, err := r.FindTraceIDs(ctx, query)
	if err != nil {
		if err == ErrNotSupported && (!query.StartTimeMax.IsZero() && !query.StartTimeMin.IsZero()) {
			return r.scanTimeRange(query.StartTimeMin, query.StartTimeMax)
		}

		return nil, err
	}

	return r.getTraces(keys)
}

// FindTraceIDs retrieves only the TraceIDs that match the traceQuery, but not the trace data
func (r *TraceReader) FindTraceIDs(ctx context.Context, query *spanstore.TraceQueryParameters) ([]model.TraceID, error) {
	// Validate and set query defaults which were not defined
	if err := validateQuery(query); err != nil {
		return nil, err
	}

	setQueryDefaults(query)

	// Find matches using indexes that are using service as part of the key
	indexSeeks := make([][]byte, 0, 1)
	indexSeeks = serviceQueries(query, indexSeeks)

	ids := make([][][]byte, 0, len(indexSeeks)+1)
	ids, err := r.indexSeeksToTraceIDs(query, indexSeeks, ids)
	if err != nil {
		return nil, err
	}

	// Only secondary range index for now (StartTime filtering should be done using the PK)
	if query.DurationMax != 0 || query.DurationMin != 0 {
		ids = r.durationQueries(query, ids)
	}

	// Transform index seeks (both unique indexes as well as non-unique indexes) to a list of TraceIDs without duplicates
	if len(ids) > 0 {
		keys := sortMergeIds(query, ids)
		return keys, nil
	}

	// TODO We could support here all the other scans, such as time range only. These are not currently backed by an index, so a "full table scan" of traces is required.
	return nil, ErrNotSupported
}

// validateQuery returns an error if certain restrictions are not met
func validateQuery(p *spanstore.TraceQueryParameters) error {
	if p == nil {
		return ErrMalformedRequestObject
	}
	if p.ServiceName == "" && len(p.Tags) > 0 {
		return ErrServiceNameNotSet
	}

	if p.ServiceName == "" && p.OperationName != "" {
		return ErrServiceNameNotSet
	}

	if p.StartTimeMin.IsZero() || p.StartTimeMax.IsZero() {
		return ErrStartAndEndTimeNotSet
	}

	if !p.StartTimeMax.IsZero() && p.StartTimeMax.Before(p.StartTimeMin) {
		return ErrStartTimeMinGreaterThanMax
	}
	if p.DurationMin != 0 && p.DurationMax != 0 && p.DurationMin > p.DurationMax {
		return ErrDurationMinGreaterThanMax
	}
	return nil
}

// scanIndexKeys scans the time range for index keys matching the given prefix.
func (r *TraceReader) scanIndexKeys(indexKeyValue []byte, startTimeMin time.Time, startTimeMax time.Time) ([][]byte, error) {
	indexResults := make([][]byte, 0)

	startStampBytes := make([]byte, 8)
	binary.BigEndian.PutUint64(startStampBytes, model.TimeAsEpochMicroseconds(startTimeMin))

	err := r.store.View(func(txn *badger.Txn) error {
		opts := badger.DefaultIteratorOptions
		opts.PrefetchValues = false // Don't fetch values since we're only interested in the keys
		it := txn.NewIterator(opts)
		defer it.Close()

		// Create starting point for sorted index scan
		startIndex := make([]byte, len(indexKeyValue)+len(startStampBytes))
		copy(startIndex, indexKeyValue)
		copy(startIndex[len(indexKeyValue):], startStampBytes)

		timeMax := model.TimeAsEpochMicroseconds(startTimeMax)
		for it.Seek(startIndex); scanFunction(it, indexKeyValue, timeMax); it.Next() {
			item := it.Item()

			// ScanFunction is a prefix scanning (since we could have for example service1 & service12)
			// Now we need to match only the exact key if we want to add it
			timestampStartIndex := len(it.Item().Key()) - (sizeOfTraceID + 8) // timestamp is stored with 8 bytes
			if bytes.Equal(indexKeyValue, it.Item().Key()[:timestampStartIndex]) {
				key := make([]byte, len(item.Key()))
				copy(key, item.Key())
				indexResults = append(indexResults, key)
			}
		}
		return nil
	})

	return indexResults, err
}

// scanFunction compares the index name as well as the time range in the index key
func scanFunction(it *badger.Iterator, indexPrefix []byte, timeIndexEnd uint64) bool {
	if it.Item() != nil {
		// We can't use the indexPrefix length, because we might have the same prefixValue for non-matching cases also
		timestampStartIndex := len(it.Item().Key()) - (sizeOfTraceID + 8) // timestamp is stored with 8 bytes
		timestamp := binary.BigEndian.Uint64(it.Item().Key()[timestampStartIndex : timestampStartIndex+8])

		return bytes.HasPrefix(it.Item().Key()[:timestampStartIndex], indexPrefix) && timestamp <= timeIndexEnd
	}
	return false
}

// scanIndexKeys scans the time range for index keys matching the given prefix.
func (r *TraceReader) scanRangeIndex(indexStartValue []byte, indexEndValue []byte, startTimeMin time.Time, startTimeMax time.Time) ([][]byte, error) {
	indexResults := make([][]byte, 0)

	startStampBytes := make([]byte, 8)
	binary.BigEndian.PutUint64(startStampBytes, model.TimeAsEpochMicroseconds(startTimeMin))

	err := r.store.View(func(txn *badger.Txn) error {
		opts := badger.DefaultIteratorOptions
		opts.PrefetchValues = false // Don't fetch values since we're only interested in the keys
		it := txn.NewIterator(opts)
		defer it.Close()

		// Create starting point for sorted index scan
		startIndex := make([]byte, len(indexStartValue)+len(startStampBytes))
		copy(startIndex, indexStartValue)
		copy(startIndex[len(indexStartValue):], startStampBytes)

		timeIndexEnd := model.TimeAsEpochMicroseconds(startTimeMax)

		for it.Seek(startIndex); scanRangeFunction(it, indexEndValue); it.Next() {
			item := it.Item()

			// ScanFunction is a prefix scanning (since we could have for example service1 & service12)
			// Now we need to match only the exact key if we want to add it
			timestampStartIndex := len(it.Item().Key()) - (sizeOfTraceID + 8) // timestamp is stored with 8 bytes
			timestamp := binary.BigEndian.Uint64(it.Item().Key()[timestampStartIndex : timestampStartIndex+8])
			if timestamp <= timeIndexEnd {
				key := make([]byte, len(item.Key()))
				copy(key, item.Key())
				indexResults = append(indexResults, key)
			}
		}
		return nil
	})
	return indexResults, err
}

// scanRangeFunction seeks until the index end has been reached
func scanRangeFunction(it *badger.Iterator, indexEndValue []byte) bool {
	if it.Item() != nil {
		compareSlice := it.Item().Key()[:len(indexEndValue)]
		return bytes.Compare(indexEndValue, compareSlice) >= 0
	}
	return false
}

// traceIDToComparableBytes transforms model.TraceID to BigEndian sorted []byte
func traceIDToComparableBytes(traceID *model.TraceID) []byte {
	traceIDBytes := make([]byte, sizeOfTraceID)
	binary.BigEndian.PutUint64(traceIDBytes, traceID.High)
	binary.BigEndian.PutUint64(traceIDBytes[8:], traceID.Low)
	return traceIDBytes
}
